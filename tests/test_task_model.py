"""Tests for the task model (TASK-050).

Pins the "actionable unit of work" (docs/02): plan-owned, optionally
outcome-serving (N:M within one plan), schedulable only once it
carries a duration.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.outcome import define_outcome
from backcasting.domain.plan import create_plan
from backcasting.domain.task import (
    Task,
    TaskError,
    create_task,
    is_schedulable,
    revise_task,
    serve_outcomes,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
REVISED = datetime(2026, 1, 2, tzinfo=timezone.utc)
DEADLINE = datetime(2026, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
TEHRAN = ZoneInfo("Asia/Tehran")


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


@pytest.fixture
def outcome(plan):
    return define_outcome(plan, "Beta released", created_at=CREATED)


class TestCreateTask:
    def test_task_starts_unestimated(self, plan) -> None:
        task = create_task(plan, "Write release notes", created_at=CREATED)
        assert task.plan_id == plan.plan_id
        assert task.title == "Write release notes"
        assert task.duration is None
        assert task.deadline is None
        assert task.outcome_ids == frozenset()

    def test_title_is_stripped(self, plan) -> None:
        task = create_task(plan, "  Write notes  ", created_at=CREATED)
        assert task.title == "Write notes"

    def test_empty_title_is_rejected(self, plan) -> None:
        for empty in ("", "   "):
            with pytest.raises(TaskError, match="non-empty"):
                create_task(plan, empty)

    def test_long_title_is_rejected(self, plan) -> None:
        with pytest.raises(TaskError, match="at most 200"):
            create_task(plan, "x" * 201)

    def test_long_description_is_rejected(self, plan) -> None:
        with pytest.raises(TaskError, match="at most 5000"):
            create_task(plan, "Title", description="x" * 5001)

    def test_zero_duration_is_rejected(self, plan) -> None:
        with pytest.raises(TaskError, match="strictly positive"):
            create_task(plan, "Title", duration=timedelta(0))

    def test_deadline_must_follow_creation(self, plan) -> None:
        with pytest.raises(TaskError, match="deadline must be after"):
            create_task(plan, "Title", deadline=CREATED - HOUR)

    def test_naive_deadline_is_rejected(self, plan) -> None:
        with pytest.raises(TaskError, match="deadline"):
            create_task(plan, "Title", deadline=datetime(2026, 3, 1))

    def test_non_utc_deadline_is_rejected(self, plan) -> None:
        with pytest.raises(TaskError, match="must be in UTC"):
            create_task(
                plan, "Title", deadline=DEADLINE.astimezone(TEHRAN)
            )

    def test_non_uuid_ids_are_rejected(self, plan) -> None:
        with pytest.raises(TaskError, match="task_id must be a UUID"):
            create_task(plan, "Title", task_id="id")
        with pytest.raises(TaskError, match="outcome_ids must contain"):
            Task(
                task_id=uuid.uuid4(),
                plan_id=plan.plan_id,
                title="Title",
                outcome_ids=frozenset({"outcome"}),  # type: ignore[arg-type]
            )

    def test_stamps_must_be_utc_and_ordered(self, plan) -> None:
        task = create_task(plan, "Title", created_at=CREATED)
        with pytest.raises(TaskError, match="must not precede"):
            Task(
                task_id=task.task_id,
                plan_id=task.plan_id,
                title="Title",
                created_at=CREATED,
                updated_at=CREATED - timedelta(seconds=1),
            )

    def test_rejects_non_plan(self) -> None:
        with pytest.raises(TypeError, match="plan must be a Plan"):
            create_task("plan", "Title")  # type: ignore[arg-type]

    def test_injectable_id_and_clock(self, plan) -> None:
        task_id = uuid.uuid4()
        task = create_task(plan, "Title", task_id=task_id, created_at=CREATED)
        assert task.task_id == task_id
        assert task.updated_at == CREATED


class TestReviseTask:
    def test_revision_moves_editable_fields(self, plan) -> None:
        task = create_task(
            plan, "Write notes", description="Draft.", created_at=CREATED
        )
        revised = revise_task(
            task,
            title="Write full release notes",
            description="Final.",
            duration=2 * HOUR,
            deadline=DEADLINE,
            updated_at=REVISED,
        )
        assert revised.title == "Write full release notes"
        assert revised.description == "Final."
        assert revised.duration == 2 * HOUR
        assert revised.deadline == DEADLINE
        assert revised.updated_at == REVISED

    def test_none_keeps_fields(self, plan) -> None:
        task = create_task(
            plan,
            "Title",
            description="Keep.",
            duration=2 * HOUR,
            deadline=DEADLINE,
            created_at=CREATED,
        )
        revised = revise_task(task, updated_at=REVISED)
        assert revised.title == task.title
        assert revised.description == "Keep."
        assert revised.duration == 2 * HOUR
        assert revised.deadline == DEADLINE

    def test_revision_carries_identity_and_links(self, plan, outcome) -> None:
        task = serve_outcomes(
            create_task(plan, "Title", created_at=CREATED),
            (outcome,),
            updated_at=REVISED,
        )
        revised = revise_task(task, title="New", updated_at=REVISED)
        assert revised.task_id == task.task_id
        assert revised.plan_id == task.plan_id
        assert revised.outcome_ids == frozenset({outcome.outcome_id})
        assert revised.created_at == task.created_at

    def test_invalid_duration_is_rejected(self, plan) -> None:
        task = create_task(plan, "Title", created_at=CREATED)
        with pytest.raises(TaskError, match="strictly positive"):
            revise_task(task, duration=-HOUR, updated_at=REVISED)

    def test_invalid_deadline_is_rejected(self, plan) -> None:
        task = create_task(plan, "Title", created_at=CREATED)
        with pytest.raises(TaskError, match="deadline must be after"):
            revise_task(task, deadline=CREATED, updated_at=REVISED)

    def test_rejects_non_task(self) -> None:
        with pytest.raises(TypeError, match="task must be a Task"):
            revise_task("task", updated_at=REVISED)  # type: ignore[arg-type]


class TestServeOutcomes:
    def test_links_outcomes(self, plan, outcome) -> None:
        task = create_task(plan, "Title", created_at=CREATED)
        linked = serve_outcomes(task, (outcome,), updated_at=REVISED)
        assert linked.outcome_ids == frozenset({outcome.outcome_id})

    def test_task_may_serve_multiple_outcomes(self, plan, outcome) -> None:
        other = define_outcome(plan, "Docs published", created_at=CREATED)
        task = create_task(plan, "Title", created_at=CREATED)
        linked = serve_outcomes(task, (outcome, other), updated_at=REVISED)
        assert linked.outcome_ids == frozenset(
            {outcome.outcome_id, other.outcome_id}
        )

    def test_linking_is_idempotent(self, plan, outcome) -> None:
        task = create_task(plan, "Title", created_at=CREATED)
        once = serve_outcomes(task, (outcome,), updated_at=REVISED)
        twice = serve_outcomes(once, (outcome,), updated_at=REVISED)
        assert twice.outcome_ids == once.outcome_ids

    def test_foreign_plans_outcome_is_rejected(self, plan, outcome) -> None:
        other_goal = create_goal(uuid.uuid4(), "Other", created_at=CREATED)
        other_plan = create_plan(other_goal, HOUR, created_at=CREATED)
        foreign = define_outcome(other_plan, "Elsewhere", created_at=CREATED)
        task = create_task(plan, "Title", created_at=CREATED)
        with pytest.raises(TaskError, match="does not belong"):
            serve_outcomes(task, (outcome, foreign), updated_at=REVISED)

    def test_non_tuple_outcomes_are_rejected(self, plan) -> None:
        task = create_task(plan, "Title", created_at=CREATED)
        with pytest.raises(TaskError, match="outcomes must be"):
            serve_outcomes(
                task, [outcome], updated_at=REVISED  # type: ignore[arg-type]
            )

    def test_rejects_non_task(self, outcome) -> None:
        with pytest.raises(TypeError, match="task must be a Task"):
            serve_outcomes(
                "task", (outcome,), updated_at=REVISED  # type: ignore[arg-type]
            )


class TestIsSchedulable:
    def test_unestimated_task_is_not_schedulable(self, plan) -> None:
        task = create_task(plan, "Title", created_at=CREATED)
        assert not is_schedulable(task)

    def test_estimated_task_is_schedulable(self, plan) -> None:
        task = create_task(plan, "Title", duration=2 * HOUR, created_at=CREATED)
        assert is_schedulable(task)

    def test_estimation_makes_it_schedulable(self, plan) -> None:
        task = create_task(plan, "Title", created_at=CREATED)
        revised = revise_task(task, duration=HOUR, updated_at=REVISED)
        assert not is_schedulable(task)
        assert is_schedulable(revised)

    def test_rejects_non_task(self) -> None:
        with pytest.raises(TypeError, match="task must be a Task"):
            is_schedulable("task")  # type: ignore[arg-type]
