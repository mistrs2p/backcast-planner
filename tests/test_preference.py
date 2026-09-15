"""Tests for preferences (TASK-043).

Pins the soft-scheduling model — weekly wall-clock windows with a
direction and weight — that the optimizer ranks candidates by. Unlike
constraints, preferences are advisory ("… → soft preferences →
optimization", docs/05); nothing here may make a slot invalid.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.preference import (
    MAX_WEIGHT,
    MIN_WEIGHT,
    Preference,
    PreferenceDirection,
    PreferenceError,
    applies_to,
    create_preference,
    preference_windows,
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


class TestPreferenceEntity:
    def test_valid_preference_is_accepted(self, calendar: Calendar) -> None:
        preference = create_preference(
            calendar,
            PreferenceDirection.PREFER,
            {0, 1, 2, 3, 4},
            time(9),
            time(12),
            created_at=CREATED,
        )
        assert preference.direction is PreferenceDirection.PREFER
        assert preference.calendar_id == calendar.calendar_id
        assert preference.weight == 3  # neutral default
        assert preference.title == ""
        assert preference.timezone is LONDON  # defaults to the calendar's

    def test_avoid_direction_is_accepted(self, calendar: Calendar) -> None:
        preference = create_preference(
            calendar,
            PreferenceDirection.AVOID,
            {5, 6},
            time(0),
            time(6),
            created_at=CREATED,
        )
        assert preference.direction is PreferenceDirection.AVOID

    def test_explicit_timezone_overrides_calendar(self, calendar: Calendar) -> None:
        preference = create_preference(
            calendar,
            PreferenceDirection.PREFER,
            {0},
            time(8),
            time(10),
            timezone=TEHRAN,
            created_at=CREATED,
        )
        assert preference.timezone is TEHRAN

    def test_non_uuid_ids_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="preference_id must be a UUID"):
            create_preference(
                calendar,
                PreferenceDirection.PREFER,
                {0},
                time(9),
                time(12),
                preference_id="id",
            )

    def test_empty_weekdays_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="weekdays must not be empty"):
            create_preference(
                calendar, PreferenceDirection.PREFER, set(), time(9), time(12)
            )

    def test_invalid_weekdays_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match=r"0 \(Monday\) to 6"):
            create_preference(
                calendar, PreferenceDirection.PREFER, {7}, time(9), time(12)
            )

    def test_naive_times_are_required(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="naive local wall-clock"):
            create_preference(
                calendar,
                PreferenceDirection.PREFER,
                {0},
                time(9, tzinfo=UTC),
                time(12),
            )

    def test_cross_midnight_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="do not cross midnight"):
            create_preference(
                calendar, PreferenceDirection.AVOID, {0}, time(22), time(6)
            )

    def test_equal_times_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="after start_time"):
            create_preference(
                calendar, PreferenceDirection.PREFER, {0}, time(9), time(9)
            )

    def test_weight_bounds(self, calendar: Calendar) -> None:
        assert MIN_WEIGHT == 1 and MAX_WEIGHT == 5
        with pytest.raises(PreferenceError, match="weight must be between"):
            create_preference(
                calendar,
                PreferenceDirection.PREFER,
                {0},
                time(9),
                time(12),
                weight=0,
            )
        with pytest.raises(PreferenceError, match="weight must be between"):
            create_preference(
                calendar,
                PreferenceDirection.PREFER,
                {0},
                time(9),
                time(12),
                weight=6,
            )
        preference = create_preference(
            calendar,
            PreferenceDirection.PREFER,
            {0},
            time(9),
            time(12),
            weight=5,
        )
        assert preference.weight == 5

    def test_bool_weight_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="weight must be an integer"):
            create_preference(
                calendar,
                PreferenceDirection.PREFER,
                {0},
                time(9),
                time(12),
                weight=True,  # type: ignore[arg-type]
            )

    def test_bad_direction_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="direction must be"):
            Preference(
                preference_id=uuid.uuid4(),
                calendar_id=calendar.calendar_id,
                direction="prefer",  # type: ignore[arg-type]
                weekdays=frozenset({0}),
                start_time=time(9),
                end_time=time(12),
            )

    def test_title_is_bounded(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="at most 200"):
            create_preference(
                calendar,
                PreferenceDirection.PREFER,
                {0},
                time(9),
                time(12),
                title="x" * 201,
            )

    def test_title_defaults_to_empty(self, calendar: Calendar) -> None:
        preference = create_preference(
            calendar,
            PreferenceDirection.PREFER,
            {0},
            time(9),
            time(12),
            title=None,  # type: ignore[arg-type]
        )
        assert preference.title == ""

    def test_stamps_must_be_utc_and_ordered(self, calendar: Calendar) -> None:
        preference = create_preference(
            calendar,
            PreferenceDirection.PREFER,
            {0},
            time(9),
            time(12),
            created_at=CREATED,
        )
        with pytest.raises(PreferenceError, match="must not precede"):
            Preference(
                preference_id=preference.preference_id,
                calendar_id=preference.calendar_id,
                direction=PreferenceDirection.PREFER,
                weekdays=frozenset({0}),
                start_time=time(9),
                end_time=time(12),
                timezone=LONDON,
                created_at=CREATED,
                updated_at=CREATED - timedelta(seconds=1),
            )


class TestPreferenceWindows:
    def _weekly(self, calendar: Calendar) -> Preference:
        # Monday–Friday 00:00–10:00 London; June is BST (UTC+1), so the
        # preferred UTC window each weekday is 23:00 prior day–09:00.
        return create_preference(
            calendar,
            PreferenceDirection.AVOID,
            {0, 1, 2, 3, 4},
            time(0),
            time(10),
            created_at=CREATED,
        )

    def test_expands_per_matching_weekday(self, calendar: Calendar) -> None:
        windows = preference_windows(
            self._weekly(calendar), range_start=WEEK_START, range_end=WEEK_END
        )
        # The UTC week [Jun 1, Jun 8) touches eight London dates (BST is
        # UTC+1): the matching weekdays are Jun 1–5 and Jun 8. The
        # boundary windows clip to the range.
        assert len(windows) == 6
        assert windows[0] == (
            datetime(2026, 6, 1, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 9, tzinfo=UTC),
        )
        assert windows[1] == (
            datetime(2026, 6, 1, 23, tzinfo=UTC),
            datetime(2026, 6, 2, 9, tzinfo=UTC),
        )
        assert windows[-1] == (
            datetime(2026, 6, 7, 23, tzinfo=UTC),
            datetime(2026, 6, 8, 0, tzinfo=UTC),
        )

    def test_non_matching_weekdays_are_skipped(self, calendar: Calendar) -> None:
        preference = create_preference(
            calendar,
            PreferenceDirection.PREFER,
            {5, 6},
            time(0),
            time(23),
            created_at=CREATED,
        )
        windows = preference_windows(
            preference, range_start=WEEK_START, range_end=WEEK_END
        )
        # Saturday Jun 6 and Sunday Jun 7 local: 00:00–23:00 local is
        # 23:00 prior day – 22:00 UTC.
        assert len(windows) == 2
        assert windows[0] == (
            datetime(2026, 6, 5, 23, tzinfo=UTC),
            datetime(2026, 6, 6, 22, tzinfo=UTC),
        )
        assert windows[1] == (
            datetime(2026, 6, 6, 23, tzinfo=UTC),
            datetime(2026, 6, 7, 22, tzinfo=UTC),
        )

    def test_clips_to_range(self, calendar: Calendar) -> None:
        windows = preference_windows(
            self._weekly(calendar),
            range_start=WEEK_START + timedelta(hours=8),  # 08:00 UTC Monday
            range_end=WEEK_START + timedelta(hours=10),
        )
        assert windows == (
            (
                WEEK_START + timedelta(hours=8),
                WEEK_START + timedelta(hours=9),
            ),
        )

    def test_wall_clock_survives_dst(self) -> None:
        tz_calendar = create_calendar(
            uuid.uuid4(), timezone=LONDON, created_at=CREATED
        )
        preference = create_preference(
            tz_calendar,
            PreferenceDirection.PREFER,
            {6},
            time(1),
            time(3),
            created_at=CREATED,
        )
        # The week of the 2026-03-29 spring-forward: Sunday 01:00–03:00
        # local spans the 01:00 jump — one real preferred hour.
        windows = preference_windows(
            preference,
            range_start=datetime(2026, 3, 23, tzinfo=UTC),
            range_end=datetime(2026, 3, 30, tzinfo=UTC),
        )
        assert windows == (
            (
                datetime(2026, 3, 29, 1, tzinfo=UTC),
                datetime(2026, 3, 29, 2, tzinfo=UTC),
            ),
        )

    def test_rejects_naive_range(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="range_start"):
            preference_windows(
                self._weekly(calendar),
                range_start=WEEK_START.replace(tzinfo=None),
                range_end=WEEK_END,
            )

    def test_rejects_empty_range(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="range_end must be after"):
            preference_windows(
                self._weekly(calendar), range_start=WEEK_START, range_end=WEEK_START
            )

    def test_rejects_non_preference(self) -> None:
        with pytest.raises(TypeError, match="preference must be a Preference"):
            preference_windows(  # type: ignore[arg-type]
                "preference", range_start=WEEK_START, range_end=WEEK_END
            )


class TestAppliesTo:
    def _prefer(self, calendar: Calendar) -> Preference:
        # Monday 09:00–12:00 London = 08:00–11:00 UTC in June (BST).
        return create_preference(
            calendar,
            PreferenceDirection.PREFER,
            {0},
            time(9),
            time(12),
            created_at=CREATED,
        )

    def test_overlapping_interval_applies(self, calendar: Calendar) -> None:
        assert applies_to(
            self._prefer(calendar),
            WEEK_START + timedelta(hours=10),
            WEEK_START + timedelta(hours=10, minutes=30),
        )

    def test_contained_interval_applies(self, calendar: Calendar) -> None:
        assert applies_to(
            self._prefer(calendar),
            WEEK_START + timedelta(hours=9),
            WEEK_START + timedelta(hours=10),
        )

    def test_outside_interval_does_not_apply(self, calendar: Calendar) -> None:
        assert not applies_to(
            self._prefer(calendar),
            WEEK_START + timedelta(hours=12),
            WEEK_START + timedelta(hours=13),
        )

    def test_touching_does_not_apply(self, calendar: Calendar) -> None:
        # Ends exactly as the window begins (08:00 UTC).
        assert not applies_to(
            self._prefer(calendar),
            WEEK_START + timedelta(hours=7),
            WEEK_START + timedelta(hours=8),
        )
        # Starts exactly as the window ends (11:00 UTC).
        assert not applies_to(
            self._prefer(calendar),
            WEEK_START + timedelta(hours=11),
            WEEK_START + timedelta(hours=12),
        )

    def test_non_matching_weekday_does_not_apply(self, calendar: Calendar) -> None:
        # Tuesday 08:00–11:00 UTC: same wall-clock time, wrong day.
        assert not applies_to(
            self._prefer(calendar),
            WEEK_START + timedelta(days=1, hours=10),
            WEEK_START + timedelta(days=1, hours=10, minutes=30),
        )

    def test_naive_interval_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="start must be timezone-aware"):
            applies_to(
                self._prefer(calendar),
                datetime(2026, 6, 1, 10),
                datetime(2026, 6, 1, 10, 30),
            )

    def test_inverted_interval_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(PreferenceError, match="end must be after start"):
            applies_to(
                self._prefer(calendar),
                WEEK_START + HOUR,
                WEEK_START,
            )


class TestFactories:
    def test_rejects_non_calendar(self) -> None:
        with pytest.raises(TypeError, match="calendar must be a Calendar"):
            create_preference(
                "calendar",  # type: ignore[arg-type]
                PreferenceDirection.PREFER,
                {0},
                time(9),
                time(12),
            )

    def test_injectable_id_and_clock(self, calendar: Calendar) -> None:
        preference_id = uuid.uuid4()
        preference = create_preference(
            calendar,
            PreferenceDirection.PREFER,
            {0},
            time(9),
            time(12),
            preference_id=preference_id,
            created_at=CREATED,
        )
        assert preference.preference_id == preference_id
        assert preference.created_at == CREATED
        assert preference.updated_at == CREATED


class TestSoftnessContract:
    def test_preference_never_rejects_a_slot(self, calendar: Calendar) -> None:
        # The defining contrast with constraints: even an AVOID
        # preference at maximum weight only *reports* applicability —
        # `applies_to` returns a bool, never raises on an overlap.
        preference = create_preference(
            calendar,
            PreferenceDirection.AVOID,
            {0, 1, 2, 3, 4, 5, 6},
            time(0),
            time(23, 59, 59),
            weight=MAX_WEIGHT,
            created_at=CREATED,
        )
        assert applies_to(
            preference,
            WEEK_START + timedelta(hours=12),
            WEEK_START + timedelta(hours=13),
        ) is True
