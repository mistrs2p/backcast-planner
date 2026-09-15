"""Tests for candidate slot generation (TASK-057).

Pins the raw material of scheduling (docs/06): free intervals a task
could fit into, with the same semantics as the capacity chain —
merged availability, in-window commitments only, DST-safe expansion,
and empty generation as fact rather than error.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.availability import create_availability_window
from backcasting.domain.calendar import create_calendar
from backcasting.domain.calendar_event import create_event
from backcasting.domain.candidate_slot import (
    CandidateSlot,
    CandidateSlotError,
    generate_candidate_slots,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
FRIDAY_END = MONDAY + timedelta(days=5)
HOUR = timedelta(hours=1)
LONDON = ZoneInfo("Europe/London")


@pytest.fixture
def calendar():
    return create_calendar(uuid.uuid4(), created_at=CREATED)


@pytest.fixture
def weekdays(calendar):
    """Monday–Friday 09:00–17:00 UTC."""
    return (
        create_availability_window(
            calendar,
            frozenset(range(5)),
            time(9),
            time(17),
            created_at=CREATED,
        ),
    )


class TestCandidateSlot:
    def test_slot_duration(self) -> None:
        slot = CandidateSlot(
            start=MONDAY.replace(hour=9),
            end=MONDAY.replace(hour=12),
        )
        assert slot.duration == 3 * HOUR

    def test_can_fit(self) -> None:
        slot = CandidateSlot(
            start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=12)
        )
        assert slot.can_fit(3 * HOUR)
        assert not slot.can_fit(3 * HOUR + timedelta(minutes=1))

    def test_zero_duration_is_rejected_in_can_fit(self) -> None:
        slot = CandidateSlot(
            start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=12)
        )
        with pytest.raises(CandidateSlotError, match="strictly positive"):
            slot.can_fit(timedelta(0))

    def test_naive_bounds_are_rejected(self) -> None:
        with pytest.raises(CandidateSlotError, match="start"):
            CandidateSlot(start=datetime(2026, 6, 1, 9), end=MONDAY)

    def test_non_utc_bounds_are_rejected(self) -> None:
        with pytest.raises(CandidateSlotError, match="must be in UTC"):
            CandidateSlot(
                start=MONDAY.replace(hour=9).astimezone(LONDON),
                end=MONDAY.replace(hour=12),
            )

    def test_inverted_bounds_are_rejected(self) -> None:
        with pytest.raises(CandidateSlotError, match="after start"):
            CandidateSlot(
                start=MONDAY.replace(hour=12), end=MONDAY.replace(hour=9)
            )


class TestGenerateCandidateSlots:
    def test_one_slot_per_available_day(self, weekdays) -> None:
        slots = generate_candidate_slots(
            weekdays,
            duration=HOUR,
            range_start=MONDAY,
            range_end=FRIDAY_END,
        )
        assert len(slots) == 5
        assert slots[0].start == MONDAY.replace(hour=9)
        assert slots[0].end == MONDAY.replace(hour=17)
        # chronological order
        starts = [slot.start for slot in slots]
        assert starts == sorted(starts)

    def test_slots_shorter_than_duration_are_dropped(self, weekdays) -> None:
        slots = generate_candidate_slots(
            weekdays,
            duration=8 * HOUR,  # window is 8h — exact fit survives
            range_start=MONDAY,
            range_end=FRIDAY_END,
        )
        assert len(slots) == 5
        too_big = generate_candidate_slots(
            weekdays,
            duration=8 * HOUR + timedelta(minutes=1),
            range_start=MONDAY,
            range_end=FRIDAY_END,
        )
        assert too_big == ()

    def test_commitments_split_slots(self, weekdays, calendar) -> None:
        meeting = create_event(
            calendar,
            "Team meeting",
            MONDAY.replace(hour=12),
            MONDAY.replace(hour=13),
            created_at=CREATED,
        )
        slots = generate_candidate_slots(
            weekdays,
            (meeting,),
            duration=HOUR,
            range_start=MONDAY,
            range_end=MONDAY + timedelta(days=1),
        )
        assert len(slots) == 2
        assert slots[0] == CandidateSlot(
            start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=12)
        )
        assert slots[1] == CandidateSlot(
            start=MONDAY.replace(hour=13), end=MONDAY.replace(hour=17)
        )

    def test_commitment_outside_availability_consumes_nothing(
        self, weekdays, calendar
    ) -> None:
        evening = create_event(
            calendar,
            "Dinner",
            MONDAY.replace(hour=19),
            MONDAY.replace(hour=21),
            created_at=CREATED,
        )
        slots = generate_candidate_slots(
            weekdays,
            (evening,),
            duration=HOUR,
            range_start=MONDAY,
            range_end=MONDAY + timedelta(days=1),
        )
        assert len(slots) == 1
        assert slots[0].duration == 8 * HOUR

    def test_commitment_covering_all_availability_leaves_nothing(
        self, weekdays, calendar
    ) -> None:
        offsite = create_event(
            calendar,
            "Offsite",
            MONDAY.replace(hour=8),
            MONDAY.replace(hour=18),
            created_at=CREATED,
        )
        slots = generate_candidate_slots(
            weekdays,
            (offsite,),
            duration=HOUR,
            range_start=MONDAY,
            range_end=MONDAY + timedelta(days=1),
        )
        assert slots == ()

    def test_touching_windows_merge_into_one_slot(self, calendar) -> None:
        morning = create_availability_window(
            calendar, frozenset(range(5)), time(9), time(12), created_at=CREATED
        )
        afternoon = create_availability_window(
            calendar, frozenset(range(5)), time(12), time(17), created_at=CREATED
        )
        slots = generate_candidate_slots(
            (morning, afternoon),
            duration=HOUR,
            range_start=MONDAY,
            range_end=MONDAY + timedelta(days=1),
        )
        assert len(slots) == 1
        assert slots[0].duration == 8 * HOUR

    def test_slots_are_clipped_to_the_range(self, weekdays) -> None:
        slots = generate_candidate_slots(
            weekdays,
            duration=HOUR,
            range_start=MONDAY.replace(hour=11),
            range_end=MONDAY.replace(hour=15),
        )
        assert len(slots) == 1
        assert slots[0].start == MONDAY.replace(hour=11)
        assert slots[0].end == MONDAY.replace(hour=15)

    def test_dst_spring_forward_loses_an_hour(self, calendar) -> None:
        """Sunday 2026-03-29, London springs forward 01:00→02:00."""
        sunday_window = create_availability_window(
            calendar,
            frozenset({6}),
            time(0),
            time(4),
            timezone=LONDON,
            created_at=CREATED,
        )
        day = datetime(2026, 3, 29, tzinfo=timezone.utc)
        plain = generate_candidate_slots(
            (sunday_window,),
            duration=HOUR,
            range_start=day,
            range_end=day + timedelta(days=1),
        )
        assert len(plain) == 1
        assert plain[0].duration == 3 * HOUR

    def test_empty_generation_is_a_fact_not_an_error(self) -> None:
        slots = generate_candidate_slots(
            (),
            duration=HOUR,
            range_start=MONDAY,
            range_end=FRIDAY_END,
        )
        assert slots == ()

    def test_reconciles_with_workable_time(self, weekdays, calendar) -> None:
        from backcasting.domain.planned_capacity import workable_time

        meeting = create_event(
            calendar,
            "Team meeting",
            MONDAY.replace(hour=12),
            MONDAY.replace(hour=13),
            created_at=CREATED,
        )
        slots = generate_candidate_slots(
            weekdays,
            (meeting,),
            duration=HOUR,
            range_start=MONDAY,
            range_end=FRIDAY_END,
        )
        total = sum((slot.duration for slot in slots), start=timedelta(0))
        assert total == workable_time(
            weekdays,
            (meeting,),
            range_start=MONDAY,
            range_end=FRIDAY_END,
        )

    def test_rejects_bad_arguments(self, weekdays, calendar) -> None:
        event = create_event(
            calendar, "E", MONDAY.replace(hour=12), MONDAY.replace(hour=13)
        )
        with pytest.raises(CandidateSlotError, match="windows must be a tuple"):
            generate_candidate_slots(
                list(weekdays),  # type: ignore[arg-type]
                duration=HOUR,
                range_start=MONDAY,
                range_end=FRIDAY_END,
            )
        with pytest.raises(CandidateSlotError, match="events must be a tuple"):
            generate_candidate_slots(
                weekdays,
                [event],  # type: ignore[arg-type]
                duration=HOUR,
                range_start=MONDAY,
                range_end=FRIDAY_END,
            )
        with pytest.raises(CandidateSlotError, match="strictly positive"):
            generate_candidate_slots(
                weekdays,
                duration=timedelta(0),
                range_start=MONDAY,
                range_end=FRIDAY_END,
            )
        with pytest.raises(CandidateSlotError, match="range_end must be after"):
            generate_candidate_slots(
                weekdays,
                duration=HOUR,
                range_start=FRIDAY_END,
                range_end=MONDAY,
            )
        with pytest.raises(CandidateSlotError, match="range_start"):
            generate_candidate_slots(
                weekdays,
                duration=HOUR,
                range_start=datetime(2026, 6, 1),
                range_end=FRIDAY_END,
            )
