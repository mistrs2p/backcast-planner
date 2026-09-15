"""Tests for hard constraint filtering of slots (TASK-058).

Pins the hierarchy's first layer (docs/05): constraints narrow or
destroy candidate slots — subtractively and absolutely ("Hard
constraints are never violated", docs/13) — with half-open semantics
so a slot ending exactly as a block begins is untouched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.calendar import create_calendar
from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.constraint import (
    create_constraint_range,
    create_constraint_weekly,
)
from backcasting.domain.constraint_filter import (
    ConstraintFilterError,
    filter_slots_by_constraints,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
TEHRAN = ZoneInfo("Asia/Tehran")


@pytest.fixture
def calendar():
    return create_calendar(uuid.uuid4(), created_at=CREATED)


@pytest.fixture
def morning_slot():
    """Monday 09:00–17:00 UTC."""
    return CandidateSlot(start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=17))


def _range(calendar, start_hour, end_hour):
    return create_constraint_range(
        calendar,
        "block",
        MONDAY.replace(hour=start_hour),
        MONDAY.replace(hour=end_hour),
        created_at=CREATED,
    )


class TestFilterSlotsByConstraints:
    def test_no_constraints_leaves_slots_untouched(self, morning_slot) -> None:
        result = filter_slots_by_constraints((morning_slot,), (), duration=HOUR)
        assert result == (morning_slot,)

    def test_weekly_constraint_narrows_a_slot(self, calendar, morning_slot) -> None:
        no_early = create_constraint_weekly(
            calendar,
            "no early work",
            frozenset(range(7)),
            time(0),
            time(10),
            created_at=CREATED,
        )
        result = filter_slots_by_constraints(
            (morning_slot,), (no_early,), duration=HOUR
        )
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=10), end=MONDAY.replace(hour=17)),
        )

    def test_range_constraint_splits_a_slot(self, calendar, morning_slot) -> None:
        lunch = _range(calendar, 12, 13)
        result = filter_slots_by_constraints((morning_slot,), (lunch,), duration=HOUR)
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=12)),
            CandidateSlot(start=MONDAY.replace(hour=13), end=MONDAY.replace(hour=17)),
        )

    def test_fully_blocked_slot_disappears(self, calendar, morning_slot) -> None:
        offsite = _range(calendar, 8, 18)
        result = filter_slots_by_constraints(
            (morning_slot,), (offsite,), duration=HOUR
        )
        assert result == ()

    def test_pieces_shorter_than_duration_disappear(
        self, calendar, morning_slot
    ) -> None:
        meeting = create_constraint_range(
            calendar,
            "meeting",
            MONDAY.replace(hour=10, minute=30),
            MONDAY.replace(hour=15, minute=30),
            created_at=CREATED,
        )
        # Pieces: 09:00–10:30 (1.5h) and 15:30–17:00 (1.5h).
        result = filter_slots_by_constraints(
            (morning_slot,), (meeting,), duration=2 * HOUR
        )
        assert result == ()
        result = filter_slots_by_constraints(
            (morning_slot,), (meeting,), duration=timedelta(minutes=90)
        )
        assert len(result) == 2

    def test_constraint_outside_the_slot_is_untouched(
        self, calendar, morning_slot
    ) -> None:
        evening = _range(calendar, 18, 20)
        result = filter_slots_by_constraints(
            (morning_slot,), (evening,), duration=HOUR
        )
        assert result == (morning_slot,)

    def test_half_open_boundary_is_allowed(self, calendar, morning_slot) -> None:
        """A block starting exactly at the slot's end removes nothing."""
        after = _range(calendar, 17, 18)
        result = filter_slots_by_constraints(
            (morning_slot,), (after,), duration=HOUR
        )
        assert result == (morning_slot,)

    def test_multiple_constraints_union(self, calendar, morning_slot) -> None:
        morning_block = _range(calendar, 9, 11)
        evening_block = _range(calendar, 16, 17)
        result = filter_slots_by_constraints(
            (morning_slot,), (morning_block, evening_block), duration=HOUR
        )
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=11), end=MONDAY.replace(hour=16)),
        )

    def test_overlapping_constraints_count_once(self, calendar, morning_slot) -> None:
        first = _range(calendar, 12, 14)
        second = _range(calendar, 13, 15)
        result = filter_slots_by_constraints(
            (morning_slot,), (first, second), duration=HOUR
        )
        # Blocked 12:00–15:00 once, not twice.
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=12)),
            CandidateSlot(start=MONDAY.replace(hour=15), end=MONDAY.replace(hour=17)),
        )

    def test_slots_stay_chronological(self, calendar) -> None:
        monday = CandidateSlot(
            start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=12)
        )
        tuesday = CandidateSlot(
            start=(MONDAY + timedelta(days=1)).replace(hour=9),
            end=(MONDAY + timedelta(days=1)).replace(hour=12),
        )
        block = _range(calendar, 9, 10)
        result = filter_slots_by_constraints(
            (monday, tuesday), (block,), duration=HOUR
        )
        starts = [slot.start for slot in result]
        assert starts == sorted(starts)
        assert len(result) == 2

    def test_weekly_constraint_honors_its_timezone(
        self, calendar, morning_slot
    ) -> None:
        """Tehran 12:30–13:30 local (UTC+3:30) blocks 09:00–10:00 UTC."""
        prayer = create_constraint_weekly(
            calendar,
            "prayer",
            frozenset(range(7)),
            time(12, 30),
            time(13, 30),
            timezone=TEHRAN,
            created_at=CREATED,
        )
        result = filter_slots_by_constraints(
            (morning_slot,), (prayer,), duration=HOUR
        )
        assert result == (
            CandidateSlot(start=MONDAY.replace(hour=10), end=MONDAY.replace(hour=17)),
        )

    def test_rejects_bad_arguments(self, morning_slot, calendar) -> None:
        constraint = _range(calendar, 12, 13)
        with pytest.raises(ConstraintFilterError, match="slots must be a tuple"):
            filter_slots_by_constraints(
                [morning_slot], (constraint,), duration=HOUR  # type: ignore[arg-type]
            )
        with pytest.raises(ConstraintFilterError, match="constraints must be a tuple"):
            filter_slots_by_constraints(
                (morning_slot,), [constraint], duration=HOUR  # type: ignore[arg-type]
            )
        with pytest.raises(ConstraintFilterError, match="strictly positive"):
            filter_slots_by_constraints(
                (morning_slot,), (constraint,), duration=timedelta(0)
            )


class TestHierarchyWiring:
    def test_slots_from_generation_then_filtered(self, calendar) -> None:
        from backcasting.domain.availability import create_availability_window
        from backcasting.domain.candidate_slot import generate_candidate_slots

        weekdays = (
            create_availability_window(
                calendar,
                frozenset(range(5)),
                time(9),
                time(17),
                created_at=CREATED,
            ),
        )
        no_early = create_constraint_weekly(
            calendar,
            "no early work",
            frozenset(range(7)),
            time(0),
            time(10),
            created_at=CREATED,
        )
        slots = generate_candidate_slots(
            weekdays,
            duration=HOUR,
            range_start=MONDAY,
            range_end=MONDAY + timedelta(days=2),
        )
        assert len(slots) == 2
        filtered = filter_slots_by_constraints(slots, (no_early,), duration=HOUR)
        assert len(filtered) == 2
        assert all(slot.start.hour == 10 for slot in filtered)
        assert all(slot.end.hour == 17 for slot in filtered)
