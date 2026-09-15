"""Tests for progress snapshots (TASK-071).

The third term of docs/07's "Planned ≠ Actual ≠ Progress": a snapshot
derives, mechanically and without judgment, where a plan stands from
its planned workload and its recorded sittings — capped at done,
with overruns left to the variance layer.
"""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.execution import create_execution
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.progress import (
    ProgressError,
    ProgressSnapshot,
    take_progress_snapshot,
)
from backcasting.domain.repositories import ProgressSnapshotRepository
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.task_estimation import TaskEstimationError

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, title, hours):
    task = create_task(plan, title, created_at=CREATED)
    return revise_task(task, duration=timedelta(hours=hours), updated_at=CREATED)


def _sitting(task, day, start_hour, end_hour):
    day = day.replace(hour=start_hour)
    return create_execution(task, day, day.replace(hour=end_hour), created_at=CREATED)


class TestTakeProgressSnapshot:
    def test_empty_plan_reports_zero_everywhere(self, plan) -> None:
        snapshot = take_progress_snapshot(plan, (), (), at=MONDAY)
        assert snapshot.plan_id == plan.plan_id
        assert snapshot.taken_at == MONDAY
        assert snapshot.task_count == 0
        assert snapshot.completed_task_count == 0
        assert snapshot.planned == timedelta(0)
        assert snapshot.actual == timedelta(0)
        assert snapshot.remaining == timedelta(0)
        assert snapshot.progress == 0.0
        assert snapshot.completion_rate == 0.0

    def test_no_work_done_yet(self, plan) -> None:
        tasks = (_task(plan, "Draft", 3), _task(plan, "Edit", 1))
        snapshot = take_progress_snapshot(plan, tasks, (), at=MONDAY)
        assert snapshot.planned == 4 * HOUR
        assert snapshot.actual == timedelta(0)
        assert snapshot.remaining == 4 * HOUR
        assert snapshot.progress == 0.0
        assert snapshot.completion_rate == 0.0

    def test_partial_progress(self, plan) -> None:
        task = _task(plan, "Draft", 4)
        sittings = (_sitting(task, MONDAY, 9, 11), _sitting(task, MONDAY, 14, 15))
        snapshot = take_progress_snapshot(
            plan, (task,), sittings, at=MONDAY.replace(hour=17)
        )
        assert snapshot.actual == 3 * HOUR
        assert snapshot.progress == 0.75
        assert snapshot.remaining == HOUR
        assert snapshot.completed_task_count == 0
        assert snapshot.completion_rate == 0.0

    def test_completed_task(self, plan) -> None:
        task = _task(plan, "Draft", 2)
        sittings = (_sitting(task, MONDAY, 9, 10), _sitting(task, MONDAY, 11, 12))
        snapshot = take_progress_snapshot(
            plan, (task,), sittings, at=MONDAY.replace(hour=17)
        )
        assert snapshot.actual == 2 * HOUR
        assert snapshot.progress == 1.0
        assert snapshot.completion_rate == 1.0
        assert snapshot.remaining == timedelta(0)

    def test_completion_is_per_task_not_per_plan(self, plan) -> None:
        """One task finished twice over does not complete its sibling."""
        done = _task(plan, "Draft", 2)
        pending = _task(plan, "Edit", 2)
        sittings = (
            _sitting(done, MONDAY, 9, 10),
            _sitting(done, MONDAY, 11, 12),
            _sitting(done, MONDAY, 14, 16),  # overwork on the done task
        )
        snapshot = take_progress_snapshot(
            plan, (done, pending), sittings, at=MONDAY.replace(hour=17)
        )
        assert snapshot.completed_task_count == 1
        assert snapshot.completion_rate == 0.5
        assert snapshot.progress == 1.0  # all planned hours worked, on one task
        assert snapshot.actual == 4 * HOUR  # the overrun stays visible here

    def test_progress_is_capped_at_one(self, plan) -> None:
        """A plan cannot be more than done; overruns are the variance
        layer's material (docs/07), not extra progress."""
        task = _task(plan, "Draft", 2)
        sittings = (_sitting(task, MONDAY, 9, 12),)
        snapshot = take_progress_snapshot(
            plan, (task,), sittings, at=MONDAY.replace(hour=17)
        )
        assert snapshot.actual == 3 * HOUR
        assert snapshot.progress == 1.0
        assert snapshot.remaining == timedelta(0)

    def test_sittings_after_the_snapshot_moment_do_not_count(self, plan) -> None:
        task = _task(plan, "Draft", 4)
        sittings = (
            _sitting(task, MONDAY, 9, 11),  # before the moment
            _sitting(task, MONDAY, 14, 16),  # ends after the moment
        )
        noon = MONDAY.replace(hour=12)
        snapshot = take_progress_snapshot(plan, (task,), sittings, at=noon)
        assert snapshot.actual == 2 * HOUR

    def test_sitting_ending_exactly_at_the_moment_counts(self, plan) -> None:
        task = _task(plan, "Draft", 4)
        sittings = (_sitting(task, MONDAY, 9, 11),)
        snapshot = take_progress_snapshot(
            plan, (task,), sittings, at=MONDAY.replace(hour=11)
        )
        assert snapshot.actual == 2 * HOUR

    def test_executions_of_other_tasks_are_ignored(self, plan) -> None:
        mine = _task(plan, "Draft", 2)
        other = _task(plan, "Edit", 2)
        sittings = (_sitting(other, MONDAY, 9, 12),)
        snapshot = take_progress_snapshot(plan, (mine,), sittings, at=MONDAY)
        assert snapshot.actual == timedelta(0)
        assert snapshot.planned == 2 * HOUR

    def test_snapshot_series_over_time(self, plan) -> None:
        """The history is a series of immutable readings, like
        CurrentState snapshots."""
        task = _task(plan, "Draft", 4)
        tuesday = MONDAY + timedelta(days=1)
        first = take_progress_snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 11),), at=tuesday
        )
        second = take_progress_snapshot(
            plan,
            (task,),
            (_sitting(task, MONDAY, 9, 11), _sitting(task, tuesday, 9, 11)),
            at=tuesday + timedelta(days=1),
        )
        assert first.progress == 0.5
        assert second.progress == 1.0
        assert first is not second

    def test_injectable_id(self, plan) -> None:
        snapshot_id = uuid.uuid4()
        snapshot = take_progress_snapshot(
            plan, (), (), at=MONDAY, snapshot_id=snapshot_id
        )
        assert snapshot.snapshot_id == snapshot_id

    def test_unestimated_task_propagates_the_estimation_error(self, plan) -> None:
        unestimated = create_task(plan, "Draft", created_at=CREATED)
        with pytest.raises(TaskEstimationError, match="has no estimate"):
            take_progress_snapshot(plan, (unestimated,), (), at=MONDAY)

    def test_rejects_task_from_another_plan(self, plan) -> None:
        other_goal = create_goal(uuid.uuid4(), "Other", created_at=CREATED)
        other_plan = create_plan(other_goal, 10 * HOUR, created_at=CREATED)
        foreign = _task(other_plan, "Foreign", 1)
        with pytest.raises(ProgressError, match="does not belong to this plan"):
            take_progress_snapshot(plan, (foreign,), (), at=MONDAY)

    def test_rejects_bad_arguments(self, plan) -> None:
        with pytest.raises(TypeError, match="plan must be a Plan"):
            take_progress_snapshot("plan", (), (), at=MONDAY)
        with pytest.raises(ProgressError, match="tasks must be a tuple"):
            take_progress_snapshot(plan, [], (), at=MONDAY)
        with pytest.raises(ProgressError, match="Task instances"):
            take_progress_snapshot(plan, ("x",), (), at=MONDAY)
        with pytest.raises(ProgressError, match="executions must be a tuple"):
            take_progress_snapshot(plan, (), [], at=MONDAY)
        with pytest.raises(ProgressError, match="Execution instances"):
            take_progress_snapshot(plan, (), ("x",), at=MONDAY)
        with pytest.raises(ProgressError, match="at must be"):
            take_progress_snapshot(plan, (), (), at=datetime(2026, 6, 1))


class TestProgressSnapshotRecord:
    def test_is_immutable(self, plan) -> None:
        snapshot = take_progress_snapshot(plan, (), (), at=MONDAY)
        with pytest.raises(FrozenInstanceError):
            snapshot.progress = 0.5  # type: ignore[misc]

    def test_direct_construction_validates(self) -> None:
        kwargs = dict(
            snapshot_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),
            taken_at=MONDAY,
            task_count=2,
            completed_task_count=1,
            planned=4 * HOUR,
            actual=2 * HOUR,
            remaining=2 * HOUR,
            progress=0.5,
            completion_rate=0.5,
        )
        assert isinstance(ProgressSnapshot(**kwargs), ProgressSnapshot)
        bad = dict(kwargs, completed_task_count=3)
        with pytest.raises(ProgressError, match="must not exceed"):
            ProgressSnapshot(**bad)
        bad = dict(kwargs, progress=1.5)
        with pytest.raises(ProgressError, match="progress must be within"):
            ProgressSnapshot(**bad)
        bad = dict(kwargs, remaining=-HOUR)
        with pytest.raises(ProgressError, match="remaining must be"):
            ProgressSnapshot(**bad)
        bad = dict(kwargs, planned="4 hours")
        with pytest.raises(ProgressError, match="planned must be"):
            ProgressSnapshot(**bad)
        bad = dict(kwargs, taken_at=datetime(2026, 6, 1))
        with pytest.raises(ProgressError, match="taken_at must be"):
            ProgressSnapshot(**bad)


class TestProgressSnapshotRepositoryPort:
    def test_in_memory_fake_honours_the_contract(self, plan) -> None:
        repo = InMemoryProgressSnapshotRepository()
        task = _task(plan, "Draft", 2)
        first = take_progress_snapshot(
            plan, (task,), (), at=MONDAY + timedelta(days=1)
        )
        second = take_progress_snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 11),), at=MONDAY
        )
        repo.save(first)
        repo.save(second)
        assert repo.get(second.snapshot_id) is second
        assert repo.get(uuid.uuid4()) is None
        assert repo.list_for_plan(plan.plan_id) == (second, first)

    def test_port_shape(self) -> None:
        assert {"save", "get", "list_for_plan"} <= set(
            ProgressSnapshotRepository.__abstractmethods__
        )


class InMemoryProgressSnapshotRepository(ProgressSnapshotRepository):
    """The reference fake: a dict keyed by id, per-plan listing."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, ProgressSnapshot] = {}

    def save(self, snapshot: ProgressSnapshot) -> None:
        self._by_id[snapshot.snapshot_id] = snapshot

    def get(self, snapshot_id: uuid.UUID) -> ProgressSnapshot | None:
        return self._by_id.get(snapshot_id)

    def list_for_plan(self, plan_id: uuid.UUID) -> tuple[ProgressSnapshot, ...]:
        return tuple(
            sorted(
                (s for s in self._by_id.values() if s.plan_id == plan_id),
                key=lambda s: s.taken_at,
            )
        )
