"""Tests for plan validation (TASK-056).

Pins pipeline step 14, "Validate" (docs/04): the whole-plan gate
before a CANDIDATE promotes to ACTIVE — ownership, estimation,
workload drift, dependency health, feasibility — plus the
max-one-active-plan rule (docs/03).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.plan import PlanStatus, create_plan, revise_plan, transition_plan
from backcasting.domain.plan_validation import (
    DEPENDENCY_CYCLE,
    EMPTY_PLAN,
    INFEASIBLE,
    TASK_OWNER_MISMATCH,
    UNESTIMATED_TASK,
    WORKLOAD_MISMATCH,
    PlanValidationError,
    activate_plan,
    validate_plan,
)
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.task_dependency import TaskDependency, add_dependency

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
PUBLISHED = datetime(2026, 1, 7, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def goal():
    return create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)


@pytest.fixture
def candidate(goal):
    plan = create_plan(goal, 3 * HOUR, created_at=CREATED)
    return transition_plan(
        revise_plan(plan, updated_at=PUBLISHED), PlanStatus.CANDIDATE, at=PUBLISHED
    )


@pytest.fixture
def tasks(candidate):
    return tuple(
        revise_task(
            create_task(candidate, f"Task {i}", created_at=PUBLISHED),
            duration=(i + 1) * HOUR,
            updated_at=PUBLISHED,
        )
        for i in range(2)
    )


def _codes(issues):
    return [issue.code for issue in issues]


class TestValidatePlan:
    def test_valid_plan_has_no_issues(self, candidate, tasks) -> None:
        issues = validate_plan(candidate, tasks, (), usable_capacity=4 * HOUR)
        assert issues == []

    def test_buffer_counts_against_capacity(self, candidate, tasks) -> None:
        issues = validate_plan(
            candidate, tasks, (), usable_capacity=3 * HOUR, buffer=HOUR
        )
        assert _codes(issues) == [INFEASIBLE]
        assert "exceeds usable capacity" in issues[0].message

    def test_infeasible_capacity_is_reported(self, candidate, tasks) -> None:
        issues = validate_plan(candidate, tasks, (), usable_capacity=2 * HOUR)
        assert _codes(issues) == [INFEASIBLE]

    def test_boundary_is_feasible(self, candidate, tasks) -> None:
        issues = validate_plan(candidate, tasks, (), usable_capacity=3 * HOUR)
        assert issues == []

    def test_foreign_task_is_reported(self, goal, candidate, tasks) -> None:
        other_plan = create_plan(goal, HOUR, created_at=CREATED)
        foreign = revise_task(
            create_task(other_plan, "Elsewhere", created_at=PUBLISHED),
            duration=HOUR,
            updated_at=PUBLISHED,
        )
        issues = validate_plan(
            candidate, tasks + (foreign,), (), usable_capacity=9 * HOUR
        )
        assert TASK_OWNER_MISMATCH in _codes(issues)

    def test_empty_plan_is_reported(self, candidate) -> None:
        issues = validate_plan(candidate, (), (), usable_capacity=HOUR)
        codes = _codes(issues)
        assert EMPTY_PLAN in codes
        # An empty plan is also trivially infeasible against its
        # recorded workload only when the workload says so; with
        # matching zero-task workload of 3h it reports infeasible here.
        assert INFEASIBLE in codes

    def test_unestimated_task_is_reported(self, candidate, tasks) -> None:
        unestimated = create_task(candidate, "No estimate", created_at=PUBLISHED)
        issues = validate_plan(
            candidate, tasks + (unestimated,), (), usable_capacity=9 * HOUR
        )
        # The estimated sum (3h) still matches the recorded workload —
        # the unestimated task is unknown, not zero — so the issue is
        # the missing estimate itself.
        assert _codes(issues) == [UNESTIMATED_TASK]

    def test_workload_drift_is_reported(self, candidate, tasks) -> None:
        drifted = revise_plan(candidate, workload=99 * HOUR, updated_at=PUBLISHED)
        issues = validate_plan(drifted, tasks, (), usable_capacity=HOUR)
        assert WORKLOAD_MISMATCH in _codes(issues)

    def test_dependency_cycle_is_reported(self, candidate, tasks) -> None:
        first, second = tasks
        # Bypass add_dependency: a corrupted collection must be
        # reported, not crash the validator.
        cycle = (
            TaskDependency(first.task_id, second.task_id),
            TaskDependency(second.task_id, first.task_id),
        )
        issues = validate_plan(candidate, tasks, cycle, usable_capacity=9 * HOUR)
        assert DEPENDENCY_CYCLE in _codes(issues)

    def test_outside_dependency_reference_is_reported(
        self, candidate, tasks
    ) -> None:
        outsider = create_task(candidate, "Outsider", created_at=PUBLISHED)
        first, _ = tasks
        links = add_dependency((), outsider, first)
        issues = validate_plan(candidate, tasks, links, usable_capacity=9 * HOUR)
        assert any(
            issue.code.startswith("dependency_reference") for issue in issues
        )

    def test_healthy_dependencies_pass(self, candidate, tasks) -> None:
        first, second = tasks
        links = add_dependency((), second, first)
        issues = validate_plan(candidate, tasks, links, usable_capacity=9 * HOUR)
        assert issues == []

    def test_all_issues_are_reported_together(self, candidate, tasks) -> None:
        unestimated = create_task(candidate, "No estimate", created_at=PUBLISHED)
        issues = validate_plan(
            candidate, tasks + (unestimated,), (), usable_capacity=HOUR
        )
        codes = _codes(issues)
        assert UNESTIMATED_TASK in codes
        assert INFEASIBLE in codes

    def test_rejects_bad_arguments(self, candidate, tasks) -> None:
        with pytest.raises(TypeError, match="plan must be a Plan"):
            validate_plan("plan", tasks, (), usable_capacity=HOUR)  # type: ignore[arg-type]
        with pytest.raises(PlanValidationError, match="tasks must be a tuple"):
            validate_plan(candidate, list(tasks), (), usable_capacity=HOUR)  # type: ignore[arg-type]


class TestActivatePlan:
    def test_candidate_activates(self, candidate, tasks) -> None:
        issues = validate_plan(candidate, tasks, (), usable_capacity=9 * HOUR)
        assert issues == []
        active = activate_plan(candidate, (), at=PUBLISHED)
        assert active.status is PlanStatus.ACTIVE
        assert active.plan_id == candidate.plan_id

    def test_draft_cannot_activate(self, goal, candidate) -> None:
        draft = create_plan(goal, HOUR, created_at=CREATED)
        with pytest.raises(PlanValidationError, match="cannot activate"):
            activate_plan(draft, (), at=PUBLISHED)

    def test_active_plan_cannot_reactivate(self, candidate) -> None:
        active = activate_plan(candidate, (), at=PUBLISHED)
        with pytest.raises(PlanValidationError, match="cannot activate"):
            activate_plan(active, (), at=PUBLISHED)

    def test_second_active_plan_is_rejected(self, goal, candidate) -> None:
        other = create_plan(goal, HOUR, created_at=CREATED)
        other_active = transition_plan(
            transition_plan(
                revise_plan(other, updated_at=PUBLISHED),
                PlanStatus.CANDIDATE,
                at=PUBLISHED,
            ),
            PlanStatus.ACTIVE,
            at=PUBLISHED,
        )
        with pytest.raises(PlanValidationError, match="already has an active plan"):
            activate_plan(candidate, (other_active,), at=PUBLISHED)

    def test_superseded_plan_does_not_block(self, goal, candidate) -> None:
        other = create_plan(goal, HOUR, created_at=CREATED)
        superseded = transition_plan(
            transition_plan(
                revise_plan(other, updated_at=PUBLISHED),
                PlanStatus.CANDIDATE,
                at=PUBLISHED,
            ),
            PlanStatus.ACTIVE,
            at=PUBLISHED,
        )
        superseded = transition_plan(superseded, PlanStatus.SUPERSEDED, at=PUBLISHED)
        active = activate_plan(candidate, (superseded,), at=PUBLISHED)
        assert active.status is PlanStatus.ACTIVE

    def test_other_goals_plans_do_not_block(self, goal, candidate) -> None:
        other_goal = create_goal(uuid.uuid4(), "Other", created_at=CREATED)
        other = create_plan(other_goal, HOUR, created_at=CREATED)
        other_active = transition_plan(
            transition_plan(
                revise_plan(other, updated_at=PUBLISHED),
                PlanStatus.CANDIDATE,
                at=PUBLISHED,
            ),
            PlanStatus.ACTIVE,
            at=PUBLISHED,
        )
        active = activate_plan(candidate, (other_active,), at=PUBLISHED)
        assert active.status is PlanStatus.ACTIVE

    def test_plan_itself_in_others_is_ignored(self, candidate) -> None:
        active = activate_plan(candidate, (candidate,), at=PUBLISHED)
        assert active.status is PlanStatus.ACTIVE

    def test_rejects_bad_arguments(self, candidate) -> None:
        with pytest.raises(TypeError, match="plan must be a Plan"):
            activate_plan("plan", ())  # type: ignore[arg-type]
        with pytest.raises(PlanValidationError, match="other_plans must be a tuple"):
            activate_plan(candidate, [])  # type: ignore[arg-type]


class TestFullFlow:
    def test_publish_validate_activate(self, goal, candidate, tasks) -> None:
        issues = validate_plan(candidate, tasks, (), usable_capacity=3 * HOUR)
        assert issues == []
        active = activate_plan(candidate, (), at=PUBLISHED)
        assert active.status is PlanStatus.ACTIVE

    def test_infeasible_plan_stays_candidate(self, candidate, tasks) -> None:
        issues = validate_plan(candidate, tasks, (), usable_capacity=HOUR)
        assert _codes(issues) == [INFEASIBLE]
        # The caller keeps the candidate a candidate; the domain does
        # not destroy the work, it reports.
        assert candidate.status is PlanStatus.CANDIDATE
