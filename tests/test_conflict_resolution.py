"""Tests for conflict resolution (TASK-065).

Pins the docs/06 principle — resolve through rescheduling, escalate
to replanning only when Plan-level feasibility is affected — and the
docs/05 hierarchy that decides who yields: commitments outrank
placements; between placements, the later-starting one yields.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.calendar import create_calendar
from backcasting.domain.calendar_event import create_event
from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.conflict_resolution import (
    ConflictResolutionError,
    Displacement,
    ResolutionAction,
    displace_between_placements,
    displace_for_commitments,
    displacements_for_task,
    resolve_displacement,
)
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.schedule import create_schedule, place_task
from backcasting.domain.task import create_task

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


@pytest.fixture
def calendar():
    return create_calendar(uuid.uuid4(), created_at=CREATED)


def _task(plan, title="Task"):
    return create_task(plan, title, created_at=CREATED)


def _schedule(plan, task=None, start_hour=9, end_hour=11, day_offset=0):
    day = MONDAY + timedelta(days=day_offset)
    return create_schedule(
        task or _task(plan),
        day.replace(hour=start_hour),
        day.replace(hour=end_hour),
        created_at=CREATED,
    )


def _event(calendar, start_hour, end_hour, day_offset=0):
    day = MONDAY + timedelta(days=day_offset)
    return create_event(
        calendar, "Meeting", day.replace(hour=start_hour),
        day.replace(hour=end_hour), created_at=CREATED,
    )


def _slot(day_offset=0, start_hour=13, end_hour=17):
    day = MONDAY + timedelta(days=day_offset)
    return CandidateSlot(
        start=day.replace(hour=start_hour), end=day.replace(hour=end_hour)
    )


class TestDisplaceForCommitments:
    def test_overlapping_event_displaces_the_schedule(
        self, plan, calendar
    ) -> None:
        schedule = _schedule(plan, start_hour=9, end_hour=11)
        event = _event(calendar, start_hour=10, end_hour=12)
        result = displace_for_commitments((schedule,), (event,))
        assert result == (
            Displacement(
                schedule=schedule,
                blocked_start=MONDAY.replace(hour=10),
                blocked_end=MONDAY.replace(hour=11),
            ),
        )

    def test_non_overlapping_event_leaves_the_schedule_alone(
        self, plan, calendar
    ) -> None:
        schedule = _schedule(plan, start_hour=9, end_hour=11)
        after = _event(calendar, start_hour=11, end_hour=12)  # back-to-back
        before = _event(calendar, start_hour=8, end_hour=9)
        assert displace_for_commitments((schedule,), (after, before)) == ()

    def test_one_event_displacing_two_schedules(self, plan, calendar) -> None:
        early = _schedule(plan, start_hour=9, end_hour=11)
        late = _schedule(plan, start_hour=10, end_hour=12)
        event = _event(calendar, start_hour=10, end_hour=11)
        result = displace_for_commitments((late, early), (event,))
        # Deterministic schedule sweep order: early first.
        assert [d.schedule for d in result] == [early, late]

    def test_two_events_overlapping_one_schedule(self, plan, calendar) -> None:
        schedule = _schedule(plan, start_hour=9, end_hour=17)
        first = _event(calendar, start_hour=10, end_hour=11)
        second = _event(calendar, start_hour=14, end_hour=15)
        result = displace_for_commitments((schedule,), (second, first))
        # One displacement per (schedule, event) pair, events in sweep order.
        assert [(d.blocked_start, d.blocked_end) for d in result] == [
            (MONDAY.replace(hour=10), MONDAY.replace(hour=11)),
            (MONDAY.replace(hour=14), MONDAY.replace(hour=15)),
        ]

    def test_rejects_bad_arguments(self, plan, calendar) -> None:
        with pytest.raises(ConflictResolutionError, match="schedules must be a tuple"):
            displace_for_commitments([], ())  # type: ignore[arg-type]
        with pytest.raises(ConflictResolutionError, match="Schedule instances"):
            displace_for_commitments(("x",), ())  # type: ignore[arg-type]
        with pytest.raises(ConflictResolutionError, match="events must be a tuple"):
            displace_for_commitments((), [])  # type: ignore[arg-type]
        with pytest.raises(ConflictResolutionError, match="CalendarEvent instances"):
            displace_for_commitments((), ("x",))  # type: ignore[arg-type]


class TestDisplaceBetweenPlacements:
    def test_later_start_yields(self, plan) -> None:
        early = _schedule(plan, start_hour=9, end_hour=11)
        late = _schedule(plan, start_hour=10, end_hour=12)
        result = displace_between_placements((late, early))
        assert [d.schedule for d in result] == [late]

    def test_blocked_interval_is_the_overlap(self, plan) -> None:
        early = _schedule(plan, start_hour=9, end_hour=12)
        late = _schedule(plan, start_hour=10, end_hour=13)
        result = displace_between_placements((early, late))
        assert result[0].blocked_start == MONDAY.replace(hour=10)
        assert result[0].blocked_end == MONDAY.replace(hour=12)

    def test_equal_starts_break_by_later_end(self, plan) -> None:
        shorter = _schedule(plan, start_hour=9, end_hour=10)
        longer = _schedule(plan, start_hour=9, end_hour=11)
        result = displace_between_placements((shorter, longer))
        assert [d.schedule for d in result] == [longer]

    def test_disjoint_placements_do_not_conflict(self, plan) -> None:
        a = _schedule(plan, start_hour=9, end_hour=11)
        b = _schedule(plan, start_hour=11, end_hour=13)  # back-to-back
        c = _schedule(plan, day_offset=1)
        assert displace_between_placements((a, b, c)) == ()

    def test_same_task_overlap_raises(self, plan) -> None:
        task = _task(plan)
        a = _schedule(plan, task, start_hour=9, end_hour=11)
        b = _schedule(plan, task, start_hour=10, end_hour=12)
        with pytest.raises(
            ConflictResolutionError, match="must not overlap"
        ):
            displace_between_placements((a, b))

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(ConflictResolutionError, match="schedules must be a tuple"):
            displace_between_placements([])  # type: ignore[arg-type]


class TestResolveDisplacement:
    def test_surviving_slots_mean_reschedule(self, plan) -> None:
        schedule = _schedule(plan)
        slots = (_slot(),)
        resolution = resolve_displacement(schedule, slots)
        assert resolution.action is ResolutionAction.RESCHEDULE
        assert resolution.slots == slots
        assert resolution.schedule is schedule
        assert resolution.reason.startswith("reschedulable")

    def test_no_slots_means_escalation(self, plan) -> None:
        schedule = _schedule(plan)
        resolution = resolve_displacement(schedule, ())
        assert resolution.action is ResolutionAction.ESCALATE_TO_REPLANNING
        assert resolution.slots == ()
        assert "NO_AVAILABLE_SLOT" in resolution.reason

    def test_rejects_bad_arguments(self, plan) -> None:
        schedule = _schedule(plan)
        with pytest.raises(ConflictResolutionError, match="schedule must be a Schedule"):
            resolve_displacement("schedule", ())  # type: ignore[arg-type]
        with pytest.raises(ConflictResolutionError, match="slots must be a tuple"):
            resolve_displacement(schedule, [])  # type: ignore[arg-type]
        with pytest.raises(ConflictResolutionError, match="CandidateSlot instances"):
            resolve_displacement(schedule, ("x",))  # type: ignore[arg-type]


class TestDisplacementsForTask:
    def test_filters_by_task(self, plan) -> None:
        task = _task(plan)
        mine = _schedule(plan, task, start_hour=9, end_hour=11)
        other = _schedule(plan, start_hour=10, end_hour=12)
        event_displaced = displace_between_placements((mine, other))
        assert displacements_for_task(event_displaced, task.task_id) == ()
        assert displacements_for_task(event_displaced, other.task_id) == (
            event_displaced[0],
        )

    def test_rejects_bad_arguments(self, plan) -> None:
        with pytest.raises(ConflictResolutionError, match="task_id must be a UUID"):
            displacements_for_task((), "task")  # type: ignore[arg-type]
        with pytest.raises(ConflictResolutionError, match="displacements must be a tuple"):
            displacements_for_task([], uuid.uuid4())  # type: ignore[arg-type]


class TestWiring:
    def test_commitment_displacement_resolves_through_rescheduling(
        self, plan, calendar
    ) -> None:
        """A new commitment displaces a placement; the task's other
        candidates decide between rescheduling and escalation."""
        from backcasting.domain.constraint import create_constraint_range
        from backcasting.domain.constraint_filter import filter_slots_by_constraints

        task = _task(plan)
        displaced = _schedule(plan, task, start_hour=9, end_hour=11)
        meeting = create_event(
            calendar, "Meeting", MONDAY.replace(hour=10), MONDAY.replace(hour=11),
            created_at=CREATED,
        )
        (displacement,) = displace_for_commitments((displaced,), (meeting,))

        # The blocked interval becomes a hard-constraint block for the
        # re-placement: the 09:00–17:00 free day minus the meeting.
        constraint = create_constraint_range(
            calendar,
            "Blocked by meeting",
            displacement.blocked_start,
            displacement.blocked_end,
            created_at=CREATED,
        )
        day = CandidateSlot(
            start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=17)
        )
        survivors = filter_slots_by_constraints(
            (day,), (constraint,), duration=HOUR
        )
        resolution = resolve_displacement(displacement.schedule, survivors)
        assert resolution.action is ResolutionAction.RESCHEDULE
        assert resolution.slots == (
            CandidateSlot(
                start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=10)
            ),
            CandidateSlot(
                start=MONDAY.replace(hour=11), end=MONDAY.replace(hour=17)
            ),
        )

    def test_no_survivors_escalates_to_replanning(self, plan, calendar) -> None:
        from backcasting.domain.constraint import create_constraint_range
        from backcasting.domain.constraint_filter import filter_slots_by_constraints

        task = _task(plan)
        displaced = _schedule(plan, task, start_hour=9, end_hour=11)
        all_day_meeting = create_event(
            calendar, "Offsite", MONDAY.replace(hour=8), MONDAY.replace(hour=20),
            created_at=CREATED,
        )
        (displacement,) = displace_for_commitments((displaced,), (all_day_meeting,))

        constraint = create_constraint_range(
            calendar,
            "Blocked by offsite",
            all_day_meeting.start,
            all_day_meeting.end,
            created_at=CREATED,
        )
        day = CandidateSlot(
            start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=17)
        )
        survivors = filter_slots_by_constraints(
            (day,), (constraint,), duration=HOUR
        )
        assert survivors == ()
        resolution = resolve_displacement(displacement.schedule, survivors)
        assert resolution.action is ResolutionAction.ESCALATE_TO_REPLANNING

    def test_displaced_parts_come_from_split_placements(
        self, plan, calendar
    ) -> None:
        """A split task's parts resolve independently."""
        from backcasting.domain.candidate_slot import CandidateSlot as Slot
        from backcasting.domain.task_splitting import split_task_across_slots

        task = _task(plan)
        slots = (
            Slot(start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=11)),
            Slot(
                start=(MONDAY + timedelta(days=1)).replace(hour=9),
                end=(MONDAY + timedelta(days=1)).replace(hour=17),
            ),
        )
        allocations = split_task_across_slots(slots, duration=4 * HOUR)
        schedules = place_task(task, allocations, created_at=CREATED)
        # Only the Monday part conflicts with the new commitment.
        meeting = create_event(
            calendar, "Meeting", MONDAY.replace(hour=10), MONDAY.replace(hour=12),
            created_at=CREATED,
        )
        result = displace_for_commitments(schedules, (meeting,))
        assert [d.schedule for d in result] == [schedules[0]]
