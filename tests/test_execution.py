"""Tests for the execution model (TASK-069).

Pins the Actual of docs/07's "Planned ≠ Actual ≠ Progress" triad:
sittings are recorded as facts — no deadline judgment, no
rounding — summed by actual_duration, and filtered per task.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.execution import (
    Execution,
    ExecutionError,
    actual_duration,
    create_execution,
    executions_for_task,
)
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.task import create_task

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, deadline=None):
    return create_task(plan, "Task", deadline=deadline, created_at=CREATED)


def _execution(task, start_hour, end_hour, day_offset=0):
    day = MONDAY + timedelta(days=day_offset)
    return create_execution(
        task, day.replace(hour=start_hour), day.replace(hour=end_hour),
        created_at=CREATED,
    )


class TestExecution:
    def test_record_shape(self, plan) -> None:
        task = _task(plan)
        execution = _execution(task, 9, 11)
        assert execution.task_id == task.task_id
        assert execution.start == MONDAY.replace(hour=9)
        assert execution.end == MONDAY.replace(hour=11)
        assert execution.duration == 2 * HOUR
        assert isinstance(execution.execution_id, uuid.UUID)

    def test_rejects_non_positive_interval(self, plan) -> None:
        task = _task(plan)
        with pytest.raises(ExecutionError, match="end must be after start"):
            _execution(task, 9, 9)

    def test_rejects_naive_datetimes(self, plan) -> None:
        task = _task(plan)
        with pytest.raises(ExecutionError, match="start must be"):
            create_execution(
                task, datetime(2026, 6, 1), MONDAY + HOUR, created_at=CREATED
            )
        with pytest.raises(ExecutionError, match="created_at must be"):
            create_execution(
                task, MONDAY, MONDAY + HOUR, created_at=datetime(2026, 1, 1)
            )

    def test_rejects_bad_task(self, plan) -> None:
        with pytest.raises(TypeError, match="task must be a Task"):
            create_execution("task", MONDAY, MONDAY + HOUR)

    def test_execution_past_the_deadline_is_recorded(self, plan) -> None:
        """No deadline judgment: the miss is the variance layer's
        material (docs/07), not a recording refusal."""
        task = _task(plan, deadline=MONDAY.replace(hour=10))
        late = _execution(task, 9, 12)
        assert late.end > task.deadline

    def test_off_granularity_durations_are_kept(self, plan) -> None:
        """Actuals are not rounded to the planning quantum."""
        task = _task(plan)
        start = MONDAY.replace(hour=9)
        end = MONDAY.replace(hour=10, minute=7)
        execution = create_execution(task, start, end, created_at=CREATED)
        assert execution.duration == timedelta(minutes=67)

    def test_execution_disjoint_from_any_schedule_is_recorded(
        self, plan
    ) -> None:
        """Planned ≠ Actual: no cross-check against placements."""
        task = _task(plan)
        elsewhere = _execution(task, 20, 22)
        assert elsewhere.start.hour == 20


class TestExecutionsForTask:
    def test_filters_by_task_keeping_input_order(self, plan) -> None:
        task = _task(plan)
        other = _task(plan)
        mine = _execution(task, 9, 10)
        theirs = _execution(other, 10, 11)
        also_mine = _execution(task, 14, 15)
        result = executions_for_task((mine, theirs, also_mine), task.task_id)
        assert result == (mine, also_mine)

    def test_rejects_bad_arguments(self, plan) -> None:
        with pytest.raises(ExecutionError, match="task_id must be a UUID"):
            executions_for_task((), "task")
        with pytest.raises(ExecutionError, match="executions must be a tuple"):
            executions_for_task([], uuid.uuid4())
        with pytest.raises(ExecutionError, match="Execution instances"):
            executions_for_task(("x",), uuid.uuid4())


class TestActualDuration:
    def test_sums_the_sittings(self, plan) -> None:
        task = _task(plan)
        total = actual_duration(
            (
                _execution(task, 9, 11),
                _execution(task, 14, 16),
                _execution(task, 9, 10, day_offset=1),
            )
        )
        assert total == 5 * HOUR

    def test_empty_sum_is_zero(self) -> None:
        assert actual_duration(()) == timedelta(0)

    def test_spans_tasks_without_segregating(self, plan) -> None:
        """The caller filters by task; the sum itself is agnostic."""
        a, b = _task(plan), _task(plan)
        total = actual_duration((_execution(a, 9, 10), _execution(b, 10, 12)))
        assert total == 3 * HOUR

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(ExecutionError, match="executions must be a tuple"):
            actual_duration([])
        with pytest.raises(ExecutionError, match="Execution instances"):
            actual_duration(("x",))


class TestWiring:
    def test_planned_versus_actual_variance_material(self, plan) -> None:
        """The triad's first two terms come from their own models."""
        from backcasting.domain.task import revise_task
        from backcasting.domain.task_estimation import (
            estimate_workload,
            record_estimation,
        )

        task = _task(plan)
        estimated = record_estimation(task, 4 * HOUR, created_at=CREATED)
        tasked = revise_task(task, duration=4 * HOUR, updated_at=CREATED)
        planned = estimate_workload((tasked,))
        actual = actual_duration(
            (_execution(task, 9, 12), _execution(task, 13, 15))
        )
        assert planned == 4 * HOUR
        assert actual == 5 * HOUR
        assert planned != actual  # the variance layer's raw material
        assert estimated.duration == tasked.duration

    def test_execution_model_mirrors_schedule_shape(self, plan) -> None:
        from backcasting.domain.schedule import create_schedule

        task = _task(plan)
        schedule = create_schedule(
            task, MONDAY.replace(hour=9), MONDAY.replace(hour=11),
            created_at=CREATED,
        )
        execution = _execution(task, 9, 13)  # ran long, as things do
        assert (schedule.start, schedule.end) == (
            MONDAY.replace(hour=9),
            MONDAY.replace(hour=11),
        )
        assert execution.duration > schedule.end - schedule.start
