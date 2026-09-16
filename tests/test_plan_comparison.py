"""Tests for plan comparison (TASK-088).

Current vs candidate under the same buffer and capacity:
feasibility first, then slack, and a no-gain candidate is not
adopted (minimum-change).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan, revise_plan
from backcasting.domain.plan_comparison import (
    PlanComparison,
    PlanComparisonError,
    PreferredPlan,
    compare_plans,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
REVISED = datetime(2026, 6, 2, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def current():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _candidate(current, hours):
    return revise_plan(
        current, workload=timedelta(hours=hours), updated_at=REVISED
    )


class TestPlanComparisonRecord:
    def _kwargs(self, current):
        from backcasting.domain.feasibility import evaluate_feasibility

        return dict(
            current=current,
            candidate=_candidate(current, 18),
            current_feasibility=evaluate_feasibility(20 * HOUR, HOUR, 40 * HOUR),
            candidate_feasibility=evaluate_feasibility(18 * HOUR, HOUR, 40 * HOUR),
            workload_delta=-2 * HOUR,
            preferred=PreferredPlan.CANDIDATE,
            reason="more-slack",
        )

    def test_shape(self, current) -> None:
        comparison = PlanComparison(**self._kwargs(current))
        assert comparison.preferred is PreferredPlan.CANDIDATE
        assert comparison.reason == "more-slack"
        assert comparison.workload_delta == -2 * HOUR

    def test_rejects_bad_fields(self, current) -> None:
        with pytest.raises(PlanComparisonError, match="current must be"):
            PlanComparison(**dict(self._kwargs(current), current="plan"))  # type: ignore[arg-type]
        with pytest.raises(PlanComparisonError, match="candidate must be a Plan"):
            PlanComparison(**dict(self._kwargs(current), candidate="plan"))  # type: ignore[arg-type]
        with pytest.raises(PlanComparisonError, match="preferred must be"):
            PlanComparison(**dict(self._kwargs(current), preferred="candidate"))  # type: ignore[arg-type]
        with pytest.raises(PlanComparisonError, match="reason must be"):
            PlanComparison(**dict(self._kwargs(current), reason="  "))
        with pytest.raises(PlanComparisonError, match="workload_delta must be"):
            PlanComparison(**dict(self._kwargs(current), workload_delta=2))  # type: ignore[arg-type]

    def test_candidate_must_be_the_same_plan(self, current) -> None:
        other = create_plan(
            create_goal(uuid.uuid4(), "Other", created_at=CREATED),
            10 * HOUR,
            created_at=CREATED,
        )
        with pytest.raises(PlanComparisonError, match="same plan"):
            PlanComparison(**dict(self._kwargs(current), candidate=other))


class TestComparePlans:
    def test_a_feasible_candidate_beats_an_infeasible_current(self, current) -> None:
        """40h capacity, 1h buffer: the 20h plan does not fit, the
        re-derived 10h one does."""
        candidate = _candidate(current, 10)
        comparison = compare_plans(
            current, candidate, buffer=HOUR, usable_capacity=11 * HOUR
        )
        assert comparison.preferred is PreferredPlan.CANDIDATE
        assert comparison.reason == "current-infeasible"
        assert comparison.current_feasibility.feasible is False
        assert comparison.candidate_feasibility.feasible is True

    def test_an_infeasible_candidate_does_not_displace_a_feasible_current(
        self, current
    ) -> None:
        candidate = _candidate(current, 30)
        comparison = compare_plans(
            current, candidate, buffer=HOUR, usable_capacity=25 * HOUR
        )
        assert comparison.preferred is PreferredPlan.CURRENT
        assert comparison.reason == "candidate-infeasible"

    def test_more_slack_wins_when_verdicts_match(self, current) -> None:
        """Same destination, cheaper path: 18h beats 20h under the
        same capacity."""
        candidate = _candidate(current, 18)
        comparison = compare_plans(
            current, candidate, buffer=HOUR, usable_capacity=40 * HOUR
        )
        assert comparison.preferred is PreferredPlan.CANDIDATE
        assert comparison.reason == "more-slack"
        assert comparison.workload_delta == -2 * HOUR
        assert (
            comparison.candidate_feasibility.slack
            - comparison.current_feasibility.slack
            == 2 * HOUR
        )

    def test_less_slack_keeps_the_current(self, current) -> None:
        candidate = _candidate(current, 22)
        comparison = compare_plans(
            current, candidate, buffer=HOUR, usable_capacity=40 * HOUR
        )
        assert comparison.preferred is PreferredPlan.CURRENT
        assert comparison.reason == "no-gain"

    def test_a_no_gain_candidate_keeps_the_current(self, current) -> None:
        """Same workload, same verdict: adopting it is change for its
        own sake — the minimum-change principle."""
        candidate = revise_plan(current, updated_at=REVISED)  # same content
        comparison = compare_plans(
            current, candidate, buffer=HOUR, usable_capacity=40 * HOUR
        )
        assert comparison.preferred is PreferredPlan.CURRENT
        assert comparison.reason == "no-gain"
        assert comparison.workload_delta == timedelta(0)

    def test_both_infeasible_compares_slack(self, current) -> None:
        """Neither fits; the closer one is still the better plan to
        work from."""
        candidate = _candidate(current, 21)
        comparison = compare_plans(
            current, candidate, buffer=HOUR, usable_capacity=10 * HOUR
        )
        assert comparison.current_feasibility.feasible is False
        assert comparison.candidate_feasibility.feasible is False
        assert comparison.preferred is PreferredPlan.CURRENT
        assert comparison.reason == "no-gain"  # 21h is farther, not closer
        closer = _candidate(current, 19)
        comparison = compare_plans(
            current, closer, buffer=HOUR, usable_capacity=10 * HOUR
        )
        assert comparison.preferred is PreferredPlan.CANDIDATE
        assert comparison.reason == "more-slack"

    def test_both_sides_share_the_capacity(self, current) -> None:
        """The comparison is honest only if both feasibility results
        come from the same buffer and capacity."""
        candidate = _candidate(current, 18)
        comparison = compare_plans(
            current, candidate, buffer=2 * HOUR, usable_capacity=30 * HOUR
        )
        assert comparison.current_feasibility.usable_capacity == 30 * HOUR
        assert comparison.candidate_feasibility.usable_capacity == 30 * HOUR
        assert comparison.current_feasibility.buffer == 2 * HOUR
        assert comparison.candidate_feasibility.buffer == 2 * HOUR

    def test_rejects_bad_arguments(self, current) -> None:
        candidate = _candidate(current, 18)
        with pytest.raises(PlanComparisonError, match="current must be"):
            compare_plans(
                "plan", candidate, buffer=HOUR, usable_capacity=40 * HOUR  # type: ignore[arg-type]
            )
        with pytest.raises(PlanComparisonError, match="candidate must be a Plan"):
            compare_plans(
                current, "plan", buffer=HOUR, usable_capacity=40 * HOUR  # type: ignore[arg-type]
            )
        with pytest.raises(PlanComparisonError, match="same plan"):
            other = create_plan(
                create_goal(uuid.uuid4(), "Other", created_at=CREATED),
                10 * HOUR,
                created_at=CREATED,
            )
            compare_plans(
                current, other, buffer=HOUR, usable_capacity=40 * HOUR
            )
        with pytest.raises(Exception, match="must be non-negative"):
            compare_plans(
                current, candidate, buffer=-HOUR, usable_capacity=40 * HOUR
            )


class TestWiring:
    def test_global_replan_candidate_through_the_comparison(self, current) -> None:
        """The full replanning arc's last joint: the global replan
        re-derives the plan, the comparison says whether to adopt
        it — here a 20h declaration that never matched its 9h task
        set, under 12h of capacity."""
        from backcasting.domain.global_replan import replan_plan_globally
        from backcasting.domain.task import create_task, revise_task

        tasks = tuple(
            revise_task(
                create_task(current, title, created_at=CREATED),
                duration=timedelta(hours=hours),
                updated_at=CREATED,
            )
            for title, hours in (("Research", 2), ("Draft", 4), ("Review", 3))
        )
        replan = replan_plan_globally(
            current, (), tasks, reason="The declared workload never matched",
            at=REVISED,
        )
        comparison = compare_plans(
            current,
            replan.plan,
            buffer=HOUR,
            usable_capacity=12 * HOUR,
        )
        assert comparison.preferred is PreferredPlan.CANDIDATE
        assert comparison.reason == "current-infeasible"
        assert comparison.workload_delta == -11 * HOUR
        assert comparison.candidate_feasibility.feasible is True
