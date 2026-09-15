"""Tests for dependency filtering of slots (TASK-060).

Pins the dependency layer of the hierarchy (docs/05): finish-to-start
as slot arithmetic — slots clip to the last prerequisite's finish, a
missing prerequisite is DEPENDENCY_BLOCKED, and only direct
prerequisites gate (transitive constraints are embodied in the
dependents' own placements).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.dependency_filter import (
    DependencyFilterError,
    filter_slots_by_dependencies,
)
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.task_dependency import add_dependency

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, title):
    return create_task(plan, title, created_at=CREATED)


def _slot(day_offset=0, start_hour=9, end_hour=17):
    day = MONDAY + timedelta(days=day_offset)
    return CandidateSlot(
        start=day.replace(hour=start_hour), end=day.replace(hour=end_hour)
    )


class TestFilterSlotsByDependencies:
    def test_task_without_prerequisites_is_untouched(self, plan) -> None:
        task = _task(plan, "Free")
        result = filter_slots_by_dependencies(
            (_slot(),),
            (),
            task_id=task.task_id,
            duration=HOUR,
            finishes={},
        )
        assert result == (_slot(),)

    def test_slot_clips_to_the_prerequisite_finish(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        links = add_dependency((), second, first)
        finishes = {first.task_id: MONDAY.replace(hour=13)}
        result = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=second.task_id,
            duration=HOUR,
            finishes=finishes,
        )
        assert result == (
            CandidateSlot(
                start=MONDAY.replace(hour=13), end=MONDAY.replace(hour=17)
            ),
        )

    def test_gate_earlier_than_the_slot_changes_nothing(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        links = add_dependency((), second, first)
        finishes = {first.task_id: MONDAY.replace(hour=7)}
        result = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=second.task_id,
            duration=HOUR,
            finishes=finishes,
        )
        assert result == (_slot(),)

    def test_latest_prerequisite_wins(self, plan) -> None:
        a = _task(plan, "A")
        b = _task(plan, "B")
        c = _task(plan, "C")
        links = add_dependency(add_dependency((), c, a), c, b)
        finishes = {
            a.task_id: MONDAY.replace(hour=10),
            b.task_id: MONDAY.replace(hour=14),
        }
        result = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=c.task_id,
            duration=HOUR,
            finishes=finishes,
        )
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=14), end=MONDAY.replace(hour=17)),
        )

    def test_missing_prerequisite_blocks_the_task(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        links = add_dependency((), second, first)
        result = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=second.task_id,
            duration=HOUR,
            finishes={},  # first not placed yet
        )
        assert result == ()

    def test_one_missing_prerequisite_blocks_even_if_others_placed(
        self, plan
    ) -> None:
        a = _task(plan, "A")
        b = _task(plan, "B")
        c = _task(plan, "C")
        links = add_dependency(add_dependency((), c, a), c, b)
        finishes = {a.task_id: MONDAY.replace(hour=10)}
        result = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=c.task_id,
            duration=HOUR,
            finishes=finishes,
        )
        assert result == ()

    def test_remainder_shorter_than_duration_is_dropped(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        links = add_dependency((), second, first)
        finishes = {first.task_id: MONDAY.replace(hour=16, minute=30)}
        result = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=second.task_id,
            duration=HOUR,
            finishes=finishes,
        )
        assert result == ()

    def test_slot_starting_exactly_at_the_finish_survives(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        links = add_dependency((), second, first)
        finishes = {first.task_id: MONDAY.replace(hour=9)}
        result = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=second.task_id,
            duration=HOUR,
            finishes=finishes,
        )
        assert result == (_slot(),)

    def test_only_direct_prerequisites_gate(self, plan) -> None:
        """C depends on B; B on A. A unplaced, B placed: not blocked."""
        a = _task(plan, "A")
        b = _task(plan, "B")
        c = _task(plan, "C")
        links = add_dependency(add_dependency((), b, a), c, b)
        finishes = {b.task_id: MONDAY.replace(hour=11)}
        result = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=c.task_id,
            duration=HOUR,
            finishes=finishes,
        )
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=11), end=MONDAY.replace(hour=17)),
        )

    def test_unrelated_tasks_finishes_are_ignored(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        other = _task(plan, "Unrelated")
        links = add_dependency((), second, first)
        finishes = {
            other.task_id: MONDAY.replace(hour=16),
            first.task_id: MONDAY.replace(hour=10),
        }
        result = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=second.task_id,
            duration=HOUR,
            finishes=finishes,
        )
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=10), end=MONDAY.replace(hour=17)),
        )

    def test_multiple_slots_keep_input_order(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        links = add_dependency((), second, first)
        finishes = {first.task_id: (MONDAY + timedelta(days=1)).replace(hour=10)}
        result = filter_slots_by_dependencies(
            (_slot(day_offset=0), _slot(day_offset=1), _slot(day_offset=2)),
            links,
            task_id=second.task_id,
            duration=HOUR,
            finishes=finishes,
        )
        # Monday's slot is entirely before the gate; Tuesday and
        # Wednesday survive, Tuesday clipped.
        assert result == (
            CandidateSlot(
                start=(MONDAY + timedelta(days=1)).replace(hour=10),
                end=(MONDAY + timedelta(days=1)).replace(hour=17),
            ),
            _slot(day_offset=2),
        )

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan, "T")
        with pytest.raises(DependencyFilterError, match="slots must be a tuple"):
            filter_slots_by_dependencies(
                [_slot()],  # type: ignore[arg-type]
                (),
                task_id=task.task_id,
                duration=HOUR,
                finishes={},
            )
        with pytest.raises(DependencyFilterError, match="task_id must be a UUID"):
            filter_slots_by_dependencies(
                (_slot(),),
                (),
                task_id="task",  # type: ignore[arg-type]
                duration=HOUR,
                finishes={},
            )
        with pytest.raises(DependencyFilterError, match="strictly positive"):
            filter_slots_by_dependencies(
                (_slot(),),
                (),
                task_id=task.task_id,
                duration=timedelta(0),
                finishes={},
            )
        with pytest.raises(DependencyFilterError, match="finishes must be a mapping"):
            filter_slots_by_dependencies(
                (_slot(),),
                (),
                task_id=task.task_id,
                duration=HOUR,
                finishes=[(task.task_id, MONDAY)],  # type: ignore[arg-type]
            )
        with pytest.raises(DependencyFilterError, match="finish"):
            filter_slots_by_dependencies(
                (_slot(),),
                (),
                task_id=task.task_id,
                duration=HOUR,
                finishes={task.task_id: datetime(2026, 6, 1, 12)},
            )


class TestWiring:
    def test_placed_task_finishes_gate_its_dependent(self, plan) -> None:
        """A placed 2h task finishing 11:00 gates its dependent."""
        drafting = revise_task(
            _task(plan, "Draft"), duration=2 * HOUR, updated_at=CREATED
        )
        review = _task(plan, "Review")
        links = add_dependency((), review, drafting)
        # The placement: drafting placed at slot start 09:00, 2h long.
        finishes = {drafting.task_id: MONDAY.replace(hour=11)}
        result = filter_slots_by_dependencies(
            (_slot(),),
            links,
            task_id=review.task_id,
            duration=HOUR,
            finishes=finishes,
        )
        assert result[0].start == MONDAY.replace(hour=11)
