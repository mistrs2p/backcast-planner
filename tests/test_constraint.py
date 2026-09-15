"""Tests for constraints (TASK-042).

Pins the hard-restriction model — fixed blocked ranges and weekly
wall-clock blocks — and the expansion/overlap semantics the scheduler
will rely on ("Hard constraints are never violated", docs/13).
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.constraint import (
    Constraint,
    ConstraintError,
    ConstraintKind,
    blocked_intervals,
    create_constraint_range,
    create_constraint_weekly,
    is_blocked,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
TEHRAN = ZoneInfo("Asia/Tehran")

# 2026-06-01 is a Monday.
MONDAY = datetime(2026, 6, 1, tzinfo=UTC)
WEEK_START = MONDAY
WEEK_END = MONDAY + timedelta(days=7)
HOUR = timedelta(hours=1)


@pytest.fixture
def calendar() -> Calendar:
    return create_calendar(uuid.uuid4(), timezone=LONDON, created_at=CREATED)


class TestConstraintRange:
    def test_valid_range_is_accepted(self, calendar: Calendar) -> None:
        constraint = create_constraint_range(
            calendar,
            "On-call",
            WEEK_START + timedelta(hours=14),
            WEEK_START + timedelta(hours=18),
            created_at=CREATED,
        )
        assert constraint.kind is ConstraintKind.BLOCKED_RANGE
        assert constraint.calendar_id == calendar.calendar_id

    def test_naive_bounds_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="timezone-aware"):
            create_constraint_range(
                calendar,
                "Naive",
                datetime(2026, 6, 1, 14),
                datetime(2026, 6, 1, 18),
            )

    def test_non_utc_bounds_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="must be in UTC"):
            create_constraint_range(
                calendar,
                "Tehran",
                datetime(2026, 6, 1, 14, tzinfo=TEHRAN),
                datetime(2026, 6, 1, 18, tzinfo=TEHRAN),
            )

    def test_inverted_range_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="end must be after start"):
            create_constraint_range(
                calendar,
                "Backwards",
                WEEK_START + timedelta(hours=18),
                WEEK_START + timedelta(hours=14),
            )

    def test_weekly_fields_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="only valid for BLOCKED_WEEKLY"):
            Constraint(
                constraint_id=uuid.uuid4(),
                calendar_id=calendar.calendar_id,
                kind=ConstraintKind.BLOCKED_RANGE,
                start=WEEK_START,
                end=WEEK_START + HOUR,
                weekdays=frozenset({0}),
            )


class TestConstraintWeekly:
    def test_valid_weekly_is_accepted(self, calendar: Calendar) -> None:
        constraint = create_constraint_weekly(
            calendar,
            "No early mornings",
            {0, 1, 2, 3, 4},
            time(0),
            time(10),
            created_at=CREATED,
        )
        assert constraint.kind is ConstraintKind.BLOCKED_WEEKLY
        assert constraint.weekdays == frozenset({0, 1, 2, 3, 4})
        assert constraint.timezone is LONDON  # defaults to the calendar's

    def test_explicit_timezone_overrides_calendar(self, calendar: Calendar) -> None:
        constraint = create_constraint_weekly(
            calendar,
            "Tehran mornings",
            {0},
            time(8),
            time(10),
            timezone=TEHRAN,
            created_at=CREATED,
        )
        assert constraint.timezone is TEHRAN

    def test_empty_weekdays_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="weekdays must not be empty"):
            create_constraint_weekly(calendar, "Empty", set(), time(0), time(10))

    def test_invalid_weekdays_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="0 \(Monday\) to 6"):
            create_constraint_weekly(calendar, "Bad", {7}, time(0), time(10))

    def test_naive_times_are_required(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="naive local wall-clock"):
            create_constraint_weekly(
                calendar,
                "Aware",
                {0},
                time(0, tzinfo=UTC),
                time(10),
            )

    def test_cross_midnight_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="cross midnight"):
            create_constraint_weekly(
                calendar, "Night", {0}, time(22), time(6)
            )

    def test_range_fields_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="only valid for BLOCKED_RANGE"):
            Constraint(
                constraint_id=uuid.uuid4(),
                calendar_id=calendar.calendar_id,
                kind=ConstraintKind.BLOCKED_WEEKLY,
                weekdays=frozenset({0}),
                start_time=time(0),
                end_time=time(10),
                start=WEEK_START,
            )


class TestSharedValidation:
    def test_non_uuid_ids_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="constraint_id must be a UUID"):
            create_constraint_range(
                calendar, "X", WEEK_START, WEEK_START + HOUR, constraint_id="id"
            )

    def test_title_is_bounded(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="at most 200"):
            create_constraint_range(
                calendar, "x" * 201, WEEK_START, WEEK_START + HOUR
            )

    def test_title_defaults_to_empty(self, calendar: Calendar) -> None:
        constraint = create_constraint_range(
            calendar, None, WEEK_START, WEEK_START + HOUR  # type: ignore[arg-type]
        )
        assert constraint.title == ""

    def test_stamps_must_be_utc_and_ordered(self, calendar: Calendar) -> None:
        constraint = create_constraint_range(
            calendar, "X", WEEK_START, WEEK_START + HOUR, created_at=CREATED
        )
        with pytest.raises(ConstraintError, match="must not precede"):
            Constraint(
                constraint_id=constraint.constraint_id,
                calendar_id=constraint.calendar_id,
                kind=ConstraintKind.BLOCKED_RANGE,
                title="X",
                start=constraint.start,
                end=constraint.end,
                created_at=CREATED,
                updated_at=CREATED - timedelta(seconds=1),
            )


class TestBlockedIntervalsRange:
    def _range(self, calendar: Calendar) -> Constraint:
        return create_constraint_range(
            calendar,
            "On-call",
            WEEK_START + timedelta(hours=14),
            WEEK_START + timedelta(hours=18),
            created_at=CREATED,
        )

    def test_expands_within_range(self, calendar: Calendar) -> None:
        intervals = blocked_intervals(
            self._range(calendar), range_start=WEEK_START, range_end=WEEK_END
        )
        assert intervals == (
            (
                WEEK_START + timedelta(hours=14),
                WEEK_START + timedelta(hours=18),
            ),
        )

    def test_clips_to_range(self, calendar: Calendar) -> None:
        intervals = blocked_intervals(
            self._range(calendar),
            range_start=WEEK_START + timedelta(hours=16),
            range_end=WEEK_START + timedelta(hours=20),
        )
        assert intervals == (
            (
                WEEK_START + timedelta(hours=16),
                WEEK_START + timedelta(hours=18),
            ),
        )

    def test_outside_range_is_empty(self, calendar: Calendar) -> None:
        intervals = blocked_intervals(
            self._range(calendar),
            range_start=WEEK_START + timedelta(days=2),
            range_end=WEEK_START + timedelta(days=3),
        )
        assert intervals == ()

    def test_rejects_naive_range(self, calendar: Calendar) -> None:
        with pytest.raises(ConstraintError, match="range_start"):
            blocked_intervals(
                self._range(calendar),
                range_start=WEEK_START.replace(tzinfo=None),
                range_end=WEEK_END,
            )


class TestBlockedIntervalsWeekly:
    def _weekly(self, calendar: Calendar) -> Constraint:
        # Monday–Friday 00:00–10:00 London; June is BST (UTC+1), so
        # the blocked UTC window each weekday is 23:00 prior day–09:00.
        return create_constraint_weekly(
            calendar,
            "No early mornings",
            {0, 1, 2, 3, 4},
            time(0),
            time(10),
            created_at=CREATED,
        )

    def test_expands_per_matching_weekday(self, calendar: Calendar) -> None:
        intervals = blocked_intervals(
            self._weekly(calendar),
            range_start=WEEK_START,
            range_end=WEEK_END,
        )
        # The UTC week [Jun 1, Jun 8) touches eight London dates (BST
        # is UTC+1): the matching weekdays are Jun 1–5 and Jun 8, each
        # blocking 00:00–10:00 local. The boundary blocks clip to the
        # range: the first loses its 23:00–00:00 UTC head, the last
        # everything after Jun 8 00:00 UTC.
        assert len(intervals) == 6
        assert intervals[0] == (
            datetime(2026, 6, 1, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 9, tzinfo=UTC),
        )
        assert intervals[1] == (
            datetime(2026, 6, 1, 23, tzinfo=UTC),
            datetime(2026, 6, 2, 9, tzinfo=UTC),
        )
        assert intervals[-1] == (
            datetime(2026, 6, 7, 23, tzinfo=UTC),
            datetime(2026, 6, 8, 0, tzinfo=UTC),
        )

    def test_non_matching_weekdays_are_skipped(self, calendar: Calendar) -> None:
        constraint = create_constraint_weekly(
            calendar, "Weekends", {5, 6}, time(0), time(23), created_at=CREATED
        )
        intervals = blocked_intervals(
            constraint, range_start=WEEK_START, range_end=WEEK_END
        )
        # Saturday Jun 6 and Sunday Jun 7 local: 00:00–23:00 local is
        # 23:00 prior day – 22:00 UTC.
        assert len(intervals) == 2
        assert intervals[0] == (
            datetime(2026, 6, 5, 23, tzinfo=UTC),
            datetime(2026, 6, 6, 22, tzinfo=UTC),
        )
        assert intervals[1] == (
            datetime(2026, 6, 6, 23, tzinfo=UTC),
            datetime(2026, 6, 7, 22, tzinfo=UTC),
        )

    def test_clips_to_range(self, calendar: Calendar) -> None:
        intervals = blocked_intervals(
            self._weekly(calendar),
            range_start=WEEK_START + timedelta(hours=8),  # 08:00 UTC Monday
            range_end=WEEK_START + timedelta(hours=10),
        )
        assert intervals == (
            (
                WEEK_START + timedelta(hours=8),
                WEEK_START + timedelta(hours=9),
            ),
        )

    def test_wall_clock_survives_dst(self) -> None:
        tz_calendar = create_calendar(
            uuid.uuid4(), timezone=LONDON, created_at=CREATED
        )
        constraint = create_constraint_weekly(
            tz_calendar, "Mornings", {6}, time(1), time(3), created_at=CREATED
        )
        # The week of the 2026-03-29 spring-forward: Sunday 01:00–03:00
        # local spans the 01:00 jump — one real hour blocked.
        intervals = blocked_intervals(
            constraint,
            range_start=datetime(2026, 3, 23, tzinfo=UTC),
            range_end=datetime(2026, 3, 30, tzinfo=UTC),
        )
        assert intervals == (
            (
                datetime(2026, 3, 29, 1, tzinfo=UTC),
                datetime(2026, 3, 29, 2, tzinfo=UTC),
            ),
        )


class TestIsBlocked:
    def test_range_overlap_is_blocked(self, calendar: Calendar) -> None:
        constraint = create_constraint_range(
            calendar, "On-call",
            WEEK_START + timedelta(hours=14),
            WEEK_START + timedelta(hours=18),
            created_at=CREATED,
        )
        assert is_blocked(
            constraint,
            WEEK_START + timedelta(hours=17),
            WEEK_START + timedelta(hours=19),
        )

    def test_outside_range_is_allowed(self, calendar: Calendar) -> None:
        constraint = create_constraint_range(
            calendar, "On-call",
            WEEK_START + timedelta(hours=14),
            WEEK_START + timedelta(hours=18),
            created_at=CREATED,
        )
        assert not is_blocked(
            constraint,
            WEEK_START + timedelta(hours=18),
            WEEK_START + timedelta(hours=19),
        )

    def test_touching_is_allowed(self, calendar: Calendar) -> None:
        constraint = create_constraint_range(
            calendar, "On-call",
            WEEK_START + timedelta(hours=14),
            WEEK_START + timedelta(hours=18),
            created_at=CREATED,
        )
        assert not is_blocked(
            constraint,
            WEEK_START + timedelta(hours=13),
            WEEK_START + timedelta(hours=14),
        )
        assert not is_blocked(
            constraint,
            WEEK_START + timedelta(hours=18),
            WEEK_START + timedelta(hours=19),
        )

    def test_containment_is_blocked(self, calendar: Calendar) -> None:
        constraint = create_constraint_range(
            calendar, "All day",
            WEEK_START,
            WEEK_START + timedelta(days=1),
            created_at=CREATED,
        )
        assert is_blocked(
            constraint,
            WEEK_START + timedelta(hours=3),
            WEEK_START + timedelta(hours=4),
        )

    def test_weekly_pattern_blocks_matching_time(self, calendar: Calendar) -> None:
        constraint = create_constraint_weekly(
            calendar, "No mornings", {0}, time(0), time(10), created_at=CREATED
        )
        # Monday 08:00 UTC = 09:00 London — inside the block.
        assert is_blocked(
            constraint,
            WEEK_START + timedelta(hours=8),
            WEEK_START + timedelta(hours=8, minutes=30),
        )
        # Monday 10:00 UTC = 11:00 London — outside the block.
        assert not is_blocked(
            constraint,
            WEEK_START + timedelta(hours=10),
            WEEK_START + timedelta(hours=11),
        )

    def test_naive_interval_is_rejected(self, calendar: Calendar) -> None:
        constraint = create_constraint_range(
            calendar, "X", WEEK_START, WEEK_START + HOUR, created_at=CREATED
        )
        with pytest.raises(ConstraintError, match="start must be timezone-aware"):
            is_blocked(
                constraint,
                datetime(2026, 6, 1, 8),
                datetime(2026, 6, 1, 9),
            )

    def test_inverted_interval_is_rejected(self, calendar: Calendar) -> None:
        constraint = create_constraint_range(
            calendar, "X", WEEK_START, WEEK_START + HOUR, created_at=CREATED
        )
        with pytest.raises(ConstraintError, match="end must be after start"):
            is_blocked(
                constraint,
                WEEK_START + HOUR,
                WEEK_START,
            )


class TestFactories:
    def test_rejects_non_calendar(self) -> None:
        with pytest.raises(TypeError, match="calendar must be a Calendar"):
            create_constraint_range(
                "calendar", "X", WEEK_START, WEEK_START + HOUR
            )
        with pytest.raises(TypeError, match="calendar must be a Calendar"):
            create_constraint_weekly("calendar", "X", {0}, time(0), time(10))

    def test_injectable_id_and_clock(self, calendar: Calendar) -> None:
        constraint_id = uuid.uuid4()
        constraint = create_constraint_range(
            calendar,
            "X",
            WEEK_START,
            WEEK_START + HOUR,
            constraint_id=constraint_id,
            created_at=CREATED,
        )
        assert constraint.constraint_id == constraint_id
        assert constraint.created_at == CREATED
        assert constraint.updated_at == CREATED
