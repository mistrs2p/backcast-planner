"""Tests for deadline handling of slots (TASK-061).

Pins the deadline layer of the hierarchy (docs/05): a deadlined task
must finish by its deadline — slots clip their ends to it, pieces
too short for the duration drop, and a task with no deadline passes
through untouched. Finishing exactly at the deadline is on time.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.deadline_filter import (
    DeadlineFilterError,
    filter_slots_by_deadline,
)
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.task import create_task

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
FRIDAY = MONDAY + timedelta(days=4)
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _slot(day_offset=0, start_hour=9, end_hour=17):
    day = MONDAY + timedelta(days=day_offset)
    return CandidateSlot(
        start=day.replace(hour=start_hour), end=day.replace(hour=end_hour)
    )


def _task(plan, deadline=None):
    return create_task(plan, "Task", deadline=deadline, created_at=CREATED)


class TestFilterSlotsByDeadline:
    def test_task_without_deadline_is_untouched(self, plan) -> None:
        task = _task(plan)
        result = filter_slots_by_deadline(
            (_slot(), _slot(day_offset=1)), task=task, duration=HOUR
        )
        assert result == (_slot(), _slot(day_offset=1))

    def test_slot_clips_to_the_deadline(self, plan) -> None:
        task = _task(plan, deadline=MONDAY.replace(hour=13))
        result = filter_slots_by_deadline((_slot(),), task=task, duration=HOUR)
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=13)),
        )

    def test_deadline_after_the_slot_changes_nothing(self, plan) -> None:
        task = _task(plan, deadline=MONDAY.replace(hour=20))
        result = filter_slots_by_deadline((_slot(),), task=task, duration=HOUR)
        assert result == (_slot(),)

    def test_finishing_exactly_at_the_deadline_is_on_time(self, plan) -> None:
        task = _task(plan, deadline=MONDAY.replace(hour=12))
        result = filter_slots_by_deadline((_slot(),), task=task, duration=3 * HOUR)
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=12)),
        )

    def test_remainder_shorter_than_duration_is_dropped(self, plan) -> None:
        task = _task(plan, deadline=MONDAY.replace(hour=10, minute=30))
        result = filter_slots_by_deadline(
            (_slot(),), task=task, duration=2 * HOUR
        )
        assert result == ()

    def test_slot_entirely_after_the_deadline_disappears(self, plan) -> None:
        task = _task(plan, deadline=MONDAY.replace(hour=12))
        result = filter_slots_by_deadline(
            (_slot(day_offset=1), _slot(day_offset=2)), task=task, duration=HOUR
        )
        assert result == ()

    def test_mixed_days_keep_only_the_prefix(self, plan) -> None:
        task = _task(plan, deadline=(MONDAY + timedelta(days=1)).replace(hour=12))
        result = filter_slots_by_deadline(
            (_slot(day_offset=0), _slot(day_offset=1), _slot(day_offset=2)),
            task=task,
            duration=HOUR,
        )
        # Monday passes whole; Tuesday survives clipped to 12:00;
        # Wednesday is entirely past the deadline.
        assert result == (
            _slot(day_offset=0),
            CandidateSlot(
                start=(MONDAY + timedelta(days=1)).replace(hour=9),
                end=(MONDAY + timedelta(days=1)).replace(hour=12),
            ),
        )

    def test_slots_keep_input_order(self, plan) -> None:
        task = _task(plan, deadline=FRIDAY.replace(hour=12))
        result = filter_slots_by_deadline(
            (_slot(day_offset=0), _slot(day_offset=1)), task=task, duration=HOUR
        )
        assert result == (_slot(day_offset=0), _slot(day_offset=1))

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan)
        with pytest.raises(DeadlineFilterError, match="slots must be a tuple"):
            filter_slots_by_deadline(
                [_slot()], task=task, duration=HOUR  # type: ignore[arg-type]
            )
        with pytest.raises(TypeError, match="task must be a Task"):
            filter_slots_by_deadline(
                (_slot(),), task="task", duration=HOUR  # type: ignore[arg-type]
            )
        with pytest.raises(DeadlineFilterError, match="strictly positive"):
            filter_slots_by_deadline(
                (_slot(),), task=task, duration=timedelta(0)
            )


class TestWiring:
    def test_deadline_composes_after_dependencies(self, plan) -> None:
        from backcasting.domain.dependency_filter import filter_slots_by_dependencies
        from backcasting.domain.task import revise_task
        from backcasting.domain.task_dependency import add_dependency

        first = create_task(plan, "Draft", created_at=CREATED)
        second = create_task(
            plan, "Review", deadline=MONDAY.replace(hour=15), created_at=CREATED
        )
        second = revise_task(second, duration=2 * HOUR, updated_at=CREATED)
        links = add_dependency((), second, first)
        finishes = {first.task_id: MONDAY.replace(hour=11)}

        gated = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=second.task_id,
            duration=2 * HOUR,
            finishes=finishes,
        )
        assert gated == (
            CandidateSlot(
                start=MONDAY.replace(hour=11), end=MONDAY.replace(hour=17)
            ),
        )
        result = filter_slots_by_deadline(gated, task=second, duration=2 * HOUR)
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=11), end=MONDAY.replace(hour=15)),
        )

    def test_dependency_gate_can_break_the_deadline(self, plan) -> None:
        """Prerequisite finishes 14:00, deadline 13:00 → conflict."""
        from backcasting.domain.dependency_filter import filter_slots_by_dependencies
        from backcasting.domain.task import revise_task
        from backcasting.domain.task_dependency import add_dependency

        first = create_task(plan, "Draft", created_at=CREATED)
        second = create_task(
            plan, "Review", deadline=MONDAY.replace(hour=13), created_at=CREATED
        )
        second = revise_task(second, duration=HOUR, updated_at=CREATED)
        links = add_dependency((), second, first)
        finishes = {first.task_id: MONDAY.replace(hour=14)}

        gated = filter_slots_by_dependencies(
            (_slot(),), links, task_id=second.task_id, duration=HOUR, finishes=finishes
        )
        # The dependency gate leaves 14:00–17:00 …
        assert gated == (
            CandidateSlot(
                start=MONDAY.replace(hour=14), end=MONDAY.replace(hour=17)
            ),
        )
        # … but the deadline clip empties it: 13:00 precedes the gate.
        result = filter_slots_by_deadline(gated, task=second, duration=HOUR)
        assert result == ()
