"""Tests for rescheduling (TASK-066).

Pins level 1 of the adaptation ladder (docs/08): "Reschedule — move
time only." The withdrawn work re-places to the tick, the untouched
placements stay put (minimum-change), and anything that would change
the workload or overlap the kept time is refused.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.rescheduling import (
    RescheduleResult,
    ReschedulingError,
    reschedule_task,
)
from backcasting.domain.schedule import Schedule, place_task
from backcasting.domain.task import create_task
from backcasting.domain.task_splitting import SlotAllocation

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
TUESDAY = MONDAY + timedelta(days=1)
HOUR = timedelta(hours=1)
LATER = datetime(2026, 7, 1, tzinfo=timezone.utc)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, deadline=None):
    return create_task(plan, "Task", deadline=deadline, created_at=CREATED)


def _schedule(task, day, start_hour, end_hour):
    return Schedule(
        schedule_id=uuid.uuid4(),
        task_id=task.task_id,
        start=day.replace(hour=start_hour),
        end=day.replace(hour=end_hour),
        created_at=CREATED,
    )


def _allocation(day, start_hour, end_hour):
    slot = CandidateSlot(
        start=day.replace(hour=start_hour), end=day.replace(hour=end_hour)
    )
    return SlotAllocation(slot=slot, start=slot.start, end=slot.end)


class TestRescheduleTask:
    def test_displaced_part_moves_untouched_part_stays(self, plan) -> None:
        """Minimum-change: only the displaced placement is replaced."""
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        tuesday = _schedule(task, TUESDAY, 9, 11)
        result = reschedule_task(
            task,
            (monday, tuesday),
            (monday,),
            (_allocation(MONDAY, 14, 16),),
            at=LATER,
        )
        assert result.removed == (monday,)
        assert result.kept == (tuesday,)
        assert len(result.placed) == 1
        (placed,) = result.placed
        assert placed.start == MONDAY.replace(hour=14)
        assert placed.end == MONDAY.replace(hour=16)

    def test_replaced_workload_is_preserved_to_the_tick(self, plan) -> None:
        """2h withdrawn, re-placed as 1h + 1h."""
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        result = reschedule_task(
            task,
            (monday,),
            (monday,),
            (
                _allocation(TUESDAY, 9, 10),
                _allocation(TUESDAY, 14, 15),
            ),
            at=LATER,
        )
        assert sum((s.end - s.start for s in result.placed), timedelta(0)) == 2 * HOUR

    def test_new_placements_share_the_reschedule_time(self, plan) -> None:
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        result = reschedule_task(
            task, (monday,), (monday,), (_allocation(TUESDAY, 9, 11),), at=LATER
        )
        assert {s.created_at for s in result.placed} == {LATER}

    def test_new_ids_are_fresh(self, plan) -> None:
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        result = reschedule_task(
            task, (monday,), (monday,), (_allocation(TUESDAY, 9, 11),), at=LATER
        )
        assert result.placed[0].schedule_id != monday.schedule_id

    def test_changing_the_workload_is_refused(self, plan) -> None:
        """Move time only — a different amount is a re-estimation."""
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)  # 2h
        with pytest.raises(ReschedulingError, match="moves time only"):
            reschedule_task(
                task, (monday,), (monday,), (_allocation(TUESDAY, 9, 12),), at=LATER
            )

    def test_new_placement_overlapping_kept_is_refused(self, plan) -> None:
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        tuesday = _schedule(task, TUESDAY, 9, 11)
        with pytest.raises(ReschedulingError, match="overlap the kept"):
            reschedule_task(
                task,
                (monday, tuesday),
                (monday,),
                (_allocation(TUESDAY, 10, 12),),  # overlaps Tuesday 09–11
                at=LATER,
            )

    def test_new_placement_back_to_back_with_kept_is_fine(self, plan) -> None:
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        tuesday = _schedule(task, TUESDAY, 9, 11)
        result = reschedule_task(
            task,
            (monday, tuesday),
            (monday,),
            (_allocation(TUESDAY, 11, 13),),
            at=LATER,
        )
        assert result.kept == (tuesday,)

    def test_deadline_is_respected_on_the_new_placement(self, plan) -> None:
        from backcasting.domain.schedule import ScheduleError

        task = _task(plan, deadline=TUESDAY.replace(hour=10))
        monday = _schedule(task, MONDAY, 9, 11)
        # place_task's ScheduleError propagates (inner-error precedent).
        with pytest.raises(ScheduleError, match="deadline"):
            reschedule_task(
                task, (monday,), (monday,), (_allocation(TUESDAY, 9, 11),), at=LATER
            )

    def test_schedules_must_belong_to_the_task(self, plan) -> None:
        task = _task(plan)
        stranger = _schedule(_task(plan), MONDAY, 9, 11)
        with pytest.raises(ReschedulingError, match="belong to the task"):
            reschedule_task(
                task, (stranger,), (stranger,), (_allocation(TUESDAY, 9, 11),), at=LATER
            )

    def test_replacing_must_be_a_subset(self, plan) -> None:
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        phantom = _schedule(task, TUESDAY, 9, 11)
        with pytest.raises(ReschedulingError, match="subset"):
            reschedule_task(
                task, (monday,), (phantom,), (_allocation(TUESDAY, 9, 11),), at=LATER
            )

    def test_nothing_to_move_is_refused(self, plan) -> None:
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        with pytest.raises(ReschedulingError, match="requires displaced"):
            reschedule_task(
                task, (monday,), (), (_allocation(TUESDAY, 9, 11),), at=LATER
            )

    def test_withdrawal_without_replacement_is_refused(self, plan) -> None:
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        with pytest.raises(ReschedulingError, match="requires new placements"):
            reschedule_task(task, (monday,), (monday,), (), at=LATER)

    def test_naive_reschedule_time_is_refused(self, plan) -> None:
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        with pytest.raises(ReschedulingError, match="at must be"):
            reschedule_task(
                task,
                (monday,),
                (monday,),
                (_allocation(TUESDAY, 9, 11),),
                at=datetime(2026, 7, 1),
            )

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        with pytest.raises(TypeError, match="task must be a Task"):
            reschedule_task(
                "task", (monday,), (monday,), (_allocation(TUESDAY, 9, 11),), at=LATER
            )
        with pytest.raises(ReschedulingError, match="schedules must be a tuple"):
            reschedule_task(
                task, [monday], (monday,), (_allocation(TUESDAY, 9, 11),), at=LATER
            )
        with pytest.raises(ReschedulingError, match="Schedule instances"):
            reschedule_task(
                task, ("x",), (monday,), (_allocation(TUESDAY, 9, 11),), at=LATER
            )
        with pytest.raises(ReschedulingError, match="SlotAllocation instances"):
            reschedule_task(
                task, (monday,), (monday,), ("x",), at=LATER
            )


class TestWiring:
    def test_conflict_to_reschedule_end_to_end(self, plan) -> None:
        """TASK-065 displacement → constraint filter → split → move."""
        from backcasting.domain.calendar import create_calendar
        from backcasting.domain.calendar_event import create_event
        from backcasting.domain.conflict_resolution import (
            displace_for_commitments,
            resolve_displacement,
            ResolutionAction,
        )
        from backcasting.domain.constraint import create_constraint_range
        from backcasting.domain.constraint_filter import filter_slots_by_constraints
        from backcasting.domain.preference_scoring import rank_slots_by_preferences
        from backcasting.domain.task_splitting import split_task_across_slots

        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        task = _task(plan)
        schedules = place_task(
            task,
            (
                _allocation(MONDAY, 9, 11),
                _allocation(TUESDAY, 9, 11),
            ),
            created_at=CREATED,
        )
        meeting = create_event(
            calendar, "Meeting", MONDAY.replace(hour=10), MONDAY.replace(hour=12),
            created_at=CREATED,
        )
        (displacement,) = displace_for_commitments(schedules, (meeting,))

        # Re-place the displaced part: the whole day minus the meeting.
        constraint = create_constraint_range(
            calendar, "Meeting", meeting.start, meeting.end, created_at=CREATED
        )
        day = CandidateSlot(
            start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=20)
        )
        survivors = filter_slots_by_constraints(
            (day,), (constraint,), duration=2 * HOUR
        )
        resolution = resolve_displacement(displacement.schedule, survivors)
        assert resolution.action is ResolutionAction.RESCHEDULE

        ranked = rank_slots_by_preferences(survivors, ())
        allocations = split_task_across_slots(ranked, duration=2 * HOUR)
        result = reschedule_task(
            task, schedules, (displacement.schedule,), allocations, at=LATER
        )
        assert result.kept == (schedules[1],)
        assert sum((s.end - s.start for s in result.placed), timedelta(0)) == 2 * HOUR
        for new in result.placed:
            assert new.start >= MONDAY.replace(hour=12) or new.end <= MONDAY.replace(
                hour=10
            )

    def test_result_feeds_the_repository(self, plan) -> None:
        """removed → delete by id; placed → save; kept stays as-is."""
        task = _task(plan)
        monday = _schedule(task, MONDAY, 9, 11)
        tuesday = _schedule(task, TUESDAY, 9, 11)
        result = reschedule_task(
            task, (monday, tuesday), (monday,), (_allocation(TUESDAY, 14, 16),),
            at=LATER,
        )
        assert isinstance(result, RescheduleResult)
        assert result.removed == (monday,)
        assert set(result.kept) | set(result.placed) == {tuesday, result.placed[0]}
