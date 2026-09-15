"""Tests for task estimation (TASK-053).

Pins pipeline step 6's task-level half (docs/04): estimates are
records with provenance (ADR-002 — proposed, then validated and
applied), and workload never sums silently over unestimated tasks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.task import create_task, is_schedulable
from backcasting.domain.task_estimation import (
    EstimationSource,
    TaskEstimation,
    TaskEstimationError,
    apply_estimation,
    estimate_workload,
    latest_estimation,
    record_estimation,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
REVISED = datetime(2026, 1, 2, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


@pytest.fixture
def task(plan):
    return create_task(plan, "Write the migration guide", created_at=CREATED)


class TestTaskEstimation:
    def test_record_carries_provenance(self, task) -> None:
        estimation = record_estimation(
            task,
            2 * HOUR,
            source=EstimationSource.AI,
            rationale="Similar guides took 2h",
            created_at=CREATED,
        )
        assert estimation.task_id == task.task_id
        assert estimation.duration == 2 * HOUR
        assert estimation.source is EstimationSource.AI
        assert estimation.rationale == "Similar guides took 2h"
        assert isinstance(estimation.estimation_id, uuid.UUID)

    def test_defaults_are_manual_and_undescribed(self, task) -> None:
        estimation = record_estimation(task, HOUR, created_at=CREATED)
        assert estimation.source is EstimationSource.MANUAL
        assert estimation.rationale == ""

    def test_rationale_is_stripped(self, task) -> None:
        estimation = record_estimation(
            task, HOUR, rationale="  why  ", created_at=CREATED
        )
        assert estimation.rationale == "why"

    def test_long_rationale_is_rejected(self, task) -> None:
        with pytest.raises(TaskEstimationError, match="at most 500"):
            record_estimation(task, HOUR, rationale="x" * 501)

    def test_non_positive_duration_is_rejected(self, task) -> None:
        for bad in (timedelta(0), -HOUR):
            with pytest.raises(TaskEstimationError, match="strictly positive"):
                record_estimation(task, bad)

    def test_non_duration_is_rejected(self, task) -> None:
        with pytest.raises(TaskEstimationError, match="strictly positive"):
            record_estimation(task, 2)  # type: ignore[arg-type]

    def test_non_uuid_ids_are_rejected(self, task) -> None:
        with pytest.raises(TaskEstimationError, match="estimation_id must be a UUID"):
            TaskEstimation(
                estimation_id="id",
                task_id=task.task_id,
                duration=HOUR,
            )
        with pytest.raises(TaskEstimationError, match="task_id must be a UUID"):
            TaskEstimation(
                estimation_id=uuid.uuid4(),
                task_id="task",
                duration=HOUR,
            )

    def test_bad_source_is_rejected(self, task) -> None:
        with pytest.raises(TaskEstimationError, match="source must be"):
            TaskEstimation(
                estimation_id=uuid.uuid4(),
                task_id=task.task_id,
                duration=HOUR,
                source="gut",  # type: ignore[arg-type]
            )

    def test_naive_created_at_is_rejected(self, task) -> None:
        with pytest.raises(TaskEstimationError, match="created_at"):
            record_estimation(task, HOUR, created_at=datetime(2026, 1, 1))

    def test_record_does_not_touch_the_task(self, task) -> None:
        record_estimation(task, 2 * HOUR, created_at=CREATED)
        assert task.duration is None
        assert not is_schedulable(task)

    def test_rejects_non_task(self) -> None:
        with pytest.raises(TypeError, match="task must be a Task"):
            record_estimation("task", HOUR)  # type: ignore[arg-type]

    def test_injectable_id(self, task) -> None:
        estimation_id = uuid.uuid4()
        estimation = record_estimation(
            task, HOUR, estimation_id=estimation_id, created_at=CREATED
        )
        assert estimation.estimation_id == estimation_id


class TestApplyEstimation:
    def test_apply_makes_the_task_schedulable(self, task) -> None:
        estimation = record_estimation(task, 2 * HOUR, created_at=CREATED)
        estimated = apply_estimation(task, estimation, updated_at=REVISED)
        assert estimated.duration == 2 * HOUR
        assert is_schedulable(estimated)
        assert estimated.updated_at == REVISED

    def test_apply_carries_identity(self, task) -> None:
        estimation = record_estimation(task, 2 * HOUR, created_at=CREATED)
        estimated = apply_estimation(task, estimation, updated_at=REVISED)
        assert estimated.task_id == task.task_id
        assert estimated.plan_id == task.plan_id
        assert estimated.title == task.title
        assert estimated.created_at == task.created_at

    def test_foreign_estimation_is_rejected(self, task, plan) -> None:
        other = create_task(plan, "Other task", created_at=CREATED)
        estimation = record_estimation(other, 2 * HOUR, created_at=CREATED)
        with pytest.raises(TaskEstimationError, match="does not belong"):
            apply_estimation(task, estimation, updated_at=REVISED)

    def test_rejects_bad_arguments(self, task) -> None:
        estimation = record_estimation(task, HOUR, created_at=CREATED)
        with pytest.raises(TypeError, match="task must be a Task"):
            apply_estimation("task", estimation, updated_at=REVISED)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="estimation must be a TaskEstimation"):
            apply_estimation(task, "estimation", updated_at=REVISED)  # type: ignore[arg-type]


class TestLatestEstimation:
    def test_none_without_records(self, task) -> None:
        assert latest_estimation((), task.task_id) is None

    def test_latest_wins(self, task) -> None:
        first = record_estimation(task, HOUR, created_at=CREATED)
        second = record_estimation(
            task, 3 * HOUR, created_at=CREATED + timedelta(days=1)
        )
        assert latest_estimation((first, second), task.task_id) is second

    def test_order_independent(self, task) -> None:
        first = record_estimation(task, HOUR, created_at=CREATED)
        second = record_estimation(
            task, 3 * HOUR, created_at=CREATED + timedelta(days=1)
        )
        assert latest_estimation((second, first), task.task_id) is second

    def test_tie_breaks_toward_the_later_position(self, task) -> None:
        first = record_estimation(task, HOUR, created_at=CREATED)
        second = record_estimation(task, 3 * HOUR, created_at=CREATED)
        assert latest_estimation((first, second), task.task_id) is second

    def test_filters_by_task(self, plan, task) -> None:
        other = create_task(plan, "Other task", created_at=CREATED)
        foreign = record_estimation(
            other, 9 * HOUR, created_at=CREATED + timedelta(days=2)
        )
        own = record_estimation(task, HOUR, created_at=CREATED)
        assert latest_estimation((foreign, own), task.task_id) is own

    def test_non_uuid_task_id_is_rejected(self, task) -> None:
        with pytest.raises(TaskEstimationError, match="task_id must be a UUID"):
            latest_estimation((), "task")

    def test_non_tuple_is_rejected(self, task) -> None:
        estimation = record_estimation(task, HOUR, created_at=CREATED)
        with pytest.raises(TaskEstimationError, match="estimations must be"):
            latest_estimation([estimation], task.task_id)  # type: ignore[arg-type]


class TestEstimateWorkload:
    def test_empty_plan_has_zero_workload(self) -> None:
        assert estimate_workload(()) == timedelta(0)

    def test_sums_estimated_durations(self, plan) -> None:
        tasks = tuple(
            create_task(plan, f"T{i}", duration=2 * HOUR, created_at=CREATED)
            for i in range(3)
        )
        assert estimate_workload(tasks) == 6 * HOUR

    def test_unestimated_task_is_rejected(self, plan, task) -> None:
        estimated = create_task(plan, "Estimated", duration=HOUR, created_at=CREATED)
        with pytest.raises(TaskEstimationError, match="has no estimate"):
            estimate_workload((estimated, task))

    def test_non_tuple_is_rejected(self, plan) -> None:
        with pytest.raises(TaskEstimationError, match="tasks must be"):
            estimate_workload([])  # type: ignore[arg-type]

    def test_non_task_is_rejected(self, plan) -> None:
        with pytest.raises(TaskEstimationError, match="Task instances"):
            estimate_workload(("task",))  # type: ignore[arg-type]


class TestPipelineWiring:
    def test_estimate_then_feasibility(self, plan, task) -> None:
        from backcasting.domain.feasibility import evaluate_feasibility

        estimation = record_estimation(task, 2 * HOUR, created_at=CREATED)
        estimated = apply_estimation(task, estimation, updated_at=REVISED)
        workload = estimate_workload((estimated,))
        result = evaluate_feasibility(workload, timedelta(0), usable_capacity=3 * HOUR)
        assert result.feasible
