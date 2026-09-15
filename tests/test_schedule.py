"""Tests for schedule persistence (TASK-064).

Pins the placement record — "Schedule: placement of task in time"
(docs/02), "Task 1:N Schedules" (docs/03) — and its persistence
port: deadline-respecting placements, no self-overlap for one task's
placements, and the repository contract (insert-or-replace by id,
None for absence, earliest-start ordering).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.repositories import ScheduleRepository
from backcasting.domain.schedule import (
    Schedule,
    ScheduleError,
    create_schedule,
    place_task,
)
from backcasting.domain.task import create_task
from backcasting.domain.task_splitting import SlotAllocation

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, deadline=None):
    return create_task(plan, "Task", deadline=deadline, created_at=CREATED)


def _allocation(day_offset=0, start_hour=9, end_hour=11):
    day = MONDAY + timedelta(days=day_offset)
    slot = CandidateSlot(
        start=day.replace(hour=start_hour), end=day.replace(hour=end_hour)
    )
    return SlotAllocation(slot=slot, start=slot.start, end=slot.end)


class InMemoryScheduleRepository(ScheduleRepository):
    def __init__(self) -> None:
        self._schedules: dict[uuid.UUID, Schedule] = {}

    def save(self, schedule: Schedule) -> None:
        self._schedules[schedule.schedule_id] = schedule

    def get(self, schedule_id: uuid.UUID) -> Schedule | None:
        return self._schedules.get(schedule_id)

    def list_for_task(self, task_id: uuid.UUID) -> list[Schedule]:
        return [
            schedule
            for schedule in sorted(
                self._schedules.values(),
                key=lambda s: (s.start, s.end, s.schedule_id),
            )
            if schedule.task_id == task_id
        ]


class TestSchedule:
    def test_record_shape(self, plan) -> None:
        task = _task(plan)
        schedule = create_schedule(
            task, MONDAY, MONDAY + HOUR, created_at=CREATED
        )
        assert schedule.task_id == task.task_id
        assert schedule.start == MONDAY
        assert schedule.end == MONDAY + HOUR
        assert schedule.created_at == CREATED
        assert isinstance(schedule.schedule_id, uuid.UUID)

    def test_rejects_non_positive_interval(self, plan) -> None:
        task = _task(plan)
        with pytest.raises(ScheduleError, match="end must be after start"):
            create_schedule(task, MONDAY, MONDAY, created_at=CREATED)

    def test_rejects_naive_datetimes(self, plan) -> None:
        task = _task(plan)
        with pytest.raises(ScheduleError, match="start must be timezone-aware"):
            create_schedule(
                task, datetime(2026, 6, 1), MONDAY + HOUR, created_at=CREATED
            )
        with pytest.raises(ScheduleError, match="created_at must be timezone-aware"):
            create_schedule(
                task, MONDAY, MONDAY + HOUR, created_at=datetime(2026, 1, 1)
            )

    def test_placement_must_respect_the_deadline(self, plan) -> None:
        task = _task(plan, deadline=MONDAY.replace(hour=12))
        with pytest.raises(ScheduleError, match="ends after the task's deadline"):
            create_schedule(
                task, MONDAY.replace(hour=11), MONDAY.replace(hour=13),
                created_at=CREATED,
            )

    def test_finishing_exactly_at_the_deadline_is_on_time(self, plan) -> None:
        task = _task(plan, deadline=MONDAY.replace(hour=11))
        schedule = create_schedule(
            task, MONDAY.replace(hour=9), MONDAY.replace(hour=11),
            created_at=CREATED,
        )
        assert schedule.end == task.deadline

    def test_task_without_deadline_places_freely(self, plan) -> None:
        task = _task(plan)
        schedule = create_schedule(
            task, MONDAY.replace(hour=23), (MONDAY + timedelta(days=2)),
            created_at=CREATED,
        )
        assert schedule.end == MONDAY + timedelta(days=2)

    def test_rejects_bad_arguments(self, plan) -> None:
        with pytest.raises(TypeError, match="task must be a Task"):
            create_schedule("task", MONDAY, MONDAY + HOUR)  # type: ignore[arg-type]


class TestPlaceTask:
    def test_one_schedule_per_allocation_in_input_order(self, plan) -> None:
        task = _task(plan)
        first, second = _allocation(day_offset=0), _allocation(day_offset=1)
        schedules = place_task(task, (first, second), created_at=CREATED)
        assert len(schedules) == 2
        assert schedules[0].start == first.start
        assert schedules[1].start == second.start
        assert all(s.task_id == task.task_id for s in schedules)

    def test_split_placements_share_one_created_at(self, plan) -> None:
        task = _task(plan)
        schedules = place_task(
            task, (_allocation(), _allocation(day_offset=1)), created_at=CREATED
        )
        assert {s.created_at for s in schedules} == {CREATED}

    def test_ids_are_fresh_and_distinct(self, plan) -> None:
        task = _task(plan)
        schedules = place_task(
            task, (_allocation(), _allocation(day_offset=1)), created_at=CREATED
        )
        assert len({s.schedule_id for s in schedules}) == 2

    def test_back_to_back_placements_are_allowed(self, plan) -> None:
        """Half-open: one part ending as the next begins is fine."""
        task = _task(plan)
        morning = _allocation(start_hour=9, end_hour=11)
        noon = _allocation(start_hour=11, end_hour=13)
        schedules = place_task(task, (morning, noon), created_at=CREATED)
        assert len(schedules) == 2

    def test_overlapping_placements_are_rejected(self, plan) -> None:
        task = _task(plan)
        morning = _allocation(start_hour=9, end_hour=12)
        noon = _allocation(start_hour=11, end_hour=13)
        with pytest.raises(ScheduleError, match="must not overlap"):
            place_task(task, (morning, noon), created_at=CREATED)

    def test_empty_allocations_are_rejected(self, plan) -> None:
        task = _task(plan)
        with pytest.raises(ScheduleError, match="must not be empty"):
            place_task(task, (), created_at=CREATED)

    def test_placement_respects_the_deadline(self, plan) -> None:
        task = _task(plan, deadline=MONDAY.replace(hour=10))
        late = _allocation(start_hour=9, end_hour=11)
        with pytest.raises(ScheduleError, match="deadline"):
            place_task(task, (late,), created_at=CREATED)

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan)
        with pytest.raises(TypeError, match="task must be a Task"):
            place_task("task", (_allocation(),))  # type: ignore[arg-type]
        with pytest.raises(ScheduleError, match="must be a tuple"):
            place_task(task, [_allocation()])  # type: ignore[arg-type]
        with pytest.raises(ScheduleError, match="SlotAllocation instances"):
            place_task(task, ("x",), created_at=CREATED)  # type: ignore[arg-type]


class TestWiring:
    def test_split_allocations_become_schedules(self, plan) -> None:
        """The TASK-063 splitter's output places directly."""
        from backcasting.domain.task_splitting import split_task_across_slots

        slots = (
            CandidateSlot(
                start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=11)
            ),
            CandidateSlot(
                start=(MONDAY + timedelta(days=1)).replace(hour=9),
                end=(MONDAY + timedelta(days=1)).replace(hour=17),
            ),
        )
        allocations = split_task_across_slots(slots, duration=4 * HOUR)
        task = _task(plan)
        schedules = place_task(task, allocations, created_at=CREATED)
        assert [s.end - s.start for s in schedules] == [2 * HOUR, 2 * HOUR]
        assert all(s.task_id == task.task_id for s in schedules)

    def test_persisted_schedules_round_trip_through_the_port(self, plan) -> None:
        repo = InMemoryScheduleRepository()
        task = _task(plan)
        schedules = place_task(
            task, (_allocation(), _allocation(day_offset=1)), created_at=CREATED
        )
        for schedule in schedules:
            repo.save(schedule)
        assert repo.get(schedules[0].schedule_id) is schedules[0]
        assert repo.get(uuid.uuid4()) is None
        assert repo.list_for_task(task.task_id) == sorted(
            schedules, key=lambda s: s.start
        )
        assert repo.list_for_task(uuid.uuid4()) == []


class TestPortShape:
    def test_interface_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            ScheduleRepository()  # type: ignore[abstract]

    def test_method_surface(self) -> None:
        for method in ("save", "get", "list_for_task"):
            assert callable(getattr(ScheduleRepository, method)), method
