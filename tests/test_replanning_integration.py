"""Replanning epic integration tests (TASK-089).

Pins EPIC-009 end to end: behavior records → progress signals →
thresholds → persistence → triggers → policy → decision → replan
scope → plan comparison → plan version — the whole adaptation
machinery of docs/08 composed over one realistic situation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from backcasting.domain.availability import create_availability_window
from backcasting.domain.calendar import create_calendar
from backcasting.domain.cooldown import Cooldown
from backcasting.domain.decision_engine import (
    DecisionAction,
    decide_response,
)
from backcasting.domain.execution import create_execution
from backcasting.domain.feedback import detect_work_outside_availability
from backcasting.domain.global_replan import replan_plan_globally
from backcasting.domain.goal import create_goal
from backcasting.domain.persistence import (
    Persistence,
    assess_persistence,
)
from backcasting.domain.plan import create_plan
from backcasting.domain.plan_comparison import PreferredPlan, compare_plans
from backcasting.domain.plan_version import latest_version
from backcasting.domain.progress import take_progress_snapshot
from backcasting.domain.replanning_policy import (
    ReplanningLevel,
    ReplanningMode,
    ReplanningPolicy,
)
from backcasting.domain.sustainability import (
    SustainabilityStatus,
    assess_sustainability,
)
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.threshold import (
    Measure,
    Threshold,
    utilization,
    variance_shortfall,
)
from backcasting.domain.trigger import (
    TriggerKind,
    raise_trigger,
    triggers_of_kind,
)
from backcasting.domain.variance import progress_variance
from backcasting.domain.velocity import compute_velocity

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)
MONDAYS = frozenset({0})


class InMemoryTriggerRepository:
    """The reference fake from TASK-079's tests, reused here."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, object] = {}

    def save(self, trigger) -> None:
        self._by_id[trigger.trigger_id] = trigger

    def get(self, trigger_id):
        return self._by_id.get(trigger_id)

    def list_all(self):
        return tuple(sorted(self._by_id.values(), key=lambda t: t.observed_at))


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    # The declared workload is wrong — the tasks actually sum to 9h.
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


@pytest.fixture
def tasks(plan):
    research = revise_task(
        create_task(plan, "Research", created_at=CREATED),
        duration=2 * HOUR, updated_at=CREATED,
    )
    draft = revise_task(
        create_task(plan, "Draft", created_at=CREATED),
        duration=4 * HOUR, updated_at=CREATED,
    )
    review = revise_task(
        create_task(plan, "Review", created_at=CREATED),
        duration=3 * HOUR, updated_at=CREATED,
    )
    return (research, draft, review)


@pytest.fixture
def availability():
    calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
    return create_availability_window(
        calendar, MONDAYS, time(9), time(17), created_at=CREATED
    )


def _sitting(task, day, start_hour, end_hour):
    day = day.replace(hour=start_hour)
    return create_execution(task, day, day.replace(hour=end_hour), created_at=CREATED)


class TestTheFullAutomaticArc:
    def test_slip_to_adopted_replan(self, plan, tasks, availability) -> None:
        """Two weeks of one hour on a 9h plan: the slip persists, the
        triggers record both facts (progress behind, evenings worked),
        the policy permits, the global replan re-derives the plan the
        tasks actually describe, and the comparison adopts it."""
        research, draft, review = tasks
        week_one = (_sitting(draft, MONDAY, 9, 10), _sitting(draft, MONDAY, 20, 21))
        week_two = week_one + (_sitting(draft, MONDAY + WEEK, 9, 10),)

        # Weekly snapshots over cumulative sittings: 2h then 3h of 9h.
        snapshots = tuple(
            take_progress_snapshot(plan, tasks, sittings, at=MONDAY + (w + 1) * WEEK)
            for w, sittings in enumerate((week_one, week_two))
        )
        hours = Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)
        magnitudes = tuple(
            variance_shortfall(progress_variance(snapshot))
            for snapshot in snapshots
        )
        assert magnitudes == (7 * HOUR, 6 * HOUR)

        policy = ReplanningPolicy(
            ReplanningMode.AUTOMATIC, Cooldown(WEEK), Persistence(2)
        )
        reading = assess_persistence(hours, magnitudes)
        assert reading.confirms(policy.persistence)

        # The two facts of the situation, as triggers on record: the
        # plan is behind, and work is happening outside the declared
        # windows — two kinds, one repository.
        at = MONDAY + 2 * WEEK
        repo = InMemoryTriggerRepository()
        repo.save(
            raise_trigger(
                TriggerKind.PROGRESS,
                f"{magnitudes[-1]} behind plan for {reading.consecutive} weeks.",
                observed_at=at,
            )
        )
        signal = detect_work_outside_availability(
            week_two, (availability,), at=at
        )
        assert signal is not None
        repo.save(
            raise_trigger(TriggerKind.BEHAVIOR, signal.statement, observed_at=at)
        )
        assert len(repo.list_all()) == 2
        assert triggers_of_kind(repo.list_all(), TriggerKind.BEHAVIOR) != ()

        # Decide, then replan globally.
        decision = decide_response(
            policy, reading, (ReplanningLevel.REPLAN,), at=at
        )
        assert decision.action is DecisionAction.ACT
        assert decision.level is ReplanningLevel.REPLAN

        replan = replan_plan_globally(
            plan, (), tasks, reason=repo.list_all()[0].detail, at=at
        )
        assert replan.plan.workload == 9 * HOUR  # re-derived, not shifted
        assert replan.version.version == 1

        # Adopt it: under 10h of capacity and a 1h buffer, the 20h
        # declaration never fit; the re-derived 9h does.
        comparison = compare_plans(
            plan, replan.plan, buffer=HOUR, usable_capacity=10 * HOUR
        )
        assert comparison.preferred is PreferredPlan.CANDIDATE
        assert comparison.reason == "current-infeasible"
        assert latest_version((replan.version,)) is replan.version

    def test_the_same_condition_waits_out_its_cooldown(
        self, plan, tasks, availability
    ) -> None:
        """The day after acting: the slip still holds, the reading
        still confirms — and the clock says hold."""
        research, draft, review = tasks
        sittings = (
            _sitting(draft, MONDAY, 9, 10),
            _sitting(draft, MONDAY + WEEK, 9, 10),
        )
        hours = Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)
        reading = assess_persistence(
            hours,
            tuple(
                variance_shortfall(
                    progress_variance(
                        take_progress_snapshot(
                            plan, tasks, sittings[: w + 1],
                            at=MONDAY + (w + 1) * WEEK,
                        )
                    )
                )
                for w in range(2)
            ),
        )
        policy = ReplanningPolicy(
            ReplanningMode.AUTOMATIC, Cooldown(WEEK), Persistence(2)
        )
        acted_at = MONDAY + 2 * WEEK

        next_day = decide_response(
            policy,
            reading,
            (ReplanningLevel.REPLAN,),
            last_offered_at=acted_at,
            at=acted_at + 24 * HOUR,
        )
        next_week = decide_response(
            policy,
            reading,
            (ReplanningLevel.REPLAN,),
            last_offered_at=acted_at,
            at=acted_at + WEEK,
        )
        assert (next_day.action, next_day.reason) == (
            DecisionAction.HOLD,
            "cooldown",
        )
        assert next_week.action is DecisionAction.ACT


class TestTheOtherModes:
    def test_suggest_mode_proposes_the_goal_revision(self, plan, tasks) -> None:
        """The destination is the problem: even confirmed and
        persistent, a goal revision is only ever proposed — the user
        changes the destination (docs/08 level 3, 'explicitly')."""
        research, draft, review = tasks
        hours = Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)
        reading = assess_persistence(hours, (8 * HOUR, 7 * HOUR))
        policy = ReplanningPolicy(
            ReplanningMode.SUGGEST, Cooldown(WEEK), Persistence(2)
        )
        decision = decide_response(
            policy,
            reading,
            (ReplanningLevel.REPLAN, ReplanningLevel.GOAL_REVISION),
            at=MONDAY + 2 * WEEK,
        )
        assert decision.action is DecisionAction.SUGGEST
        assert decision.level is ReplanningLevel.REPLAN  # minimum-change

        goal_decision = decide_response(
            policy,
            reading,
            (ReplanningLevel.GOAL_REVISION,),
            at=MONDAY + 2 * WEEK,
        )
        assert goal_decision.action is DecisionAction.SUGGEST
        assert goal_decision.level is ReplanningLevel.GOAL_REVISION

    def test_manual_mode_touches_nothing(self, plan, tasks) -> None:
        reading = assess_persistence(
            Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR),
            (8 * HOUR, 7 * HOUR),
        )
        policy = ReplanningPolicy(
            ReplanningMode.MANUAL, Cooldown(WEEK), Persistence(2)
        )
        decision = decide_response(
            policy, reading, (ReplanningLevel.REPLAN,), at=MONDAY + 2 * WEEK
        )
        assert (decision.action, decision.reason) == (
            DecisionAction.HOLD,
            "manual-mode",
        )


class TestStability:
    def test_one_bad_week_is_noise(self, plan, tasks) -> None:
        """A slow first week followed by a recovery raises no
        confirmed condition: the clear resets the run, and nothing
        is decided, triggered, or versioned."""
        research, draft, review = tasks
        slow_start = (_sitting(draft, MONDAY, 9, 10),)  # 1h of 9h: 8h slip
        recovered = slow_start + (
            _sitting(draft, MONDAY + WEEK, 9, 16),  # +7h: cumulative 8h, 1h slip
        )
        magnitudes = tuple(
            variance_shortfall(
                progress_variance(
                    take_progress_snapshot(
                        plan, tasks, sittings, at=MONDAY + (w + 1) * WEEK
                    )
                )
            )
            for w, sittings in enumerate((slow_start, recovered))
        )
        assert magnitudes == (8 * HOUR, 1 * HOUR)
        reading = assess_persistence(
            Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR), magnitudes
        )
        assert (reading.active, reading.consecutive) == (False, 0)
        policy = ReplanningPolicy(
            ReplanningMode.AUTOMATIC, Cooldown(WEEK), Persistence(2)
        )
        decision = decide_response(
            policy, reading, (ReplanningLevel.REPLAN,), at=MONDAY + 2 * WEEK
        )
        assert (decision.action, decision.reason) == (
            DecisionAction.HOLD,
            "not-persistent",
        )

    def test_hysteresis_holds_through_the_dip(self, plan, tasks) -> None:
        """Three weeks behind, the middle one recovering into the gap
        (between exit and enter): the condition never cleared, so the
        run counts on."""
        research, draft, review = tasks
        week_one = (_sitting(draft, MONDAY, 9, 10),)  # cumulative 1h: 8h slip
        week_two = week_one + (_sitting(draft, MONDAY + WEEK, 9, 13),)  # 5h: 4h slip
        week_three = week_two + (_sitting(draft, MONDAY + 2 * WEEK, 9, 10),)  # 6h: 3h
        magnitudes = tuple(
            variance_shortfall(
                progress_variance(
                    take_progress_snapshot(
                        plan, tasks, sittings, at=MONDAY + (w + 1) * WEEK
                    )
                )
            )
            for w, sittings in enumerate((week_one, week_two, week_three))
        )
        assert magnitudes == (8 * HOUR, 4 * HOUR, 3 * HOUR)
        reading = assess_persistence(
            Threshold(Measure.SHORTFALL, 6 * HOUR, 2 * HOUR), magnitudes
        )
        assert reading.active is True
        assert reading.consecutive == 3
        assert reading.confirms(Persistence(3))


class TestOverworkArc:
    def test_burnout_arithmetic_raises_the_behavior_fact(
        self, plan, tasks, availability
    ) -> None:
        """The other direction of adaptation: work is happening —
        the full declared window plus evenings, two weeks running.
        Sustainability's arithmetic says unsustainable, the
        utilization threshold crosses, and the behavior trigger puts
        the evening hours on record."""
        research, draft, review = tasks
        crunch = tuple(
            sitting
            for week in (MONDAY, MONDAY + WEEK)
            for sitting in (
                _sitting(draft, week, 9, 17),  # the whole declared window
                _sitting(draft, week, 19, 21),  # and the evening besides
            )
        )
        at = MONDAY + 2 * WEEK
        velocity = compute_velocity(crunch, at=at, window=2 * WEEK)
        assert velocity.worked == 20 * HOUR

        sustainability = assess_sustainability(velocity, (availability,))
        assert sustainability.status is SustainabilityStatus.UNSUSTAINABLE
        assert sustainability.workable == 16 * HOUR

        # The utilization adapter feeds the same threshold machinery
        # the shortfall does — one vocabulary, both directions.
        overuse = Threshold(Measure.UTILIZATION, 1.0, 0.8)
        reading = assess_persistence(overuse, (utilization(sustainability),) * 2)
        assert reading.confirms(Persistence(2))

        signal = detect_work_outside_availability(crunch, (availability,), at=at)
        assert signal is not None
        repo = InMemoryTriggerRepository()
        repo.save(
            raise_trigger(
                TriggerKind.BEHAVIOR, signal.statement, observed_at=at
            )
        )
        # Overwork is a suggestion to the user, not an act: the pace
        # is theirs to change (docs/08 — the behavior trigger feeds
        # the reasoning layer; the domain does not force a replan).
        policy = ReplanningPolicy(
            ReplanningMode.SUGGEST, Cooldown(WEEK), Persistence(2)
        )
        decision = decide_response(
            policy, reading, (ReplanningLevel.REPLAN,), at=at
        )
        assert decision.action is DecisionAction.SUGGEST
        assert decision.level is ReplanningLevel.REPLAN
