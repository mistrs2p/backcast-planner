"""Tests for timezone handling (TASK-035).

Pins the shared timezone semantics: UTC validation and normalization,
wall-clock interpretation/display (docs/10), DST kind classification,
and Monday-anchored week bounds in a user's zone.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.timezone import (
    LocalTimeKind,
    TimezoneError,
    instant_from_wall_clock,
    local_time,
    local_time_kind,
    require_utc,
    to_utc,
    week_bounds,
)

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
TEHRAN = ZoneInfo("Asia/Tehran")


class CustomError(ValueError):
    pass


class TestRequireUtc:
    def test_accepts_utc_instants(self) -> None:
        require_utc("stamp", datetime(2026, 1, 5, 9, tzinfo=UTC))
        require_utc("stamp", datetime(2026, 1, 5, 9, tzinfo=ZoneInfo("UTC")))

    def test_rejects_naive_datetimes(self) -> None:
        with pytest.raises(TimezoneError, match="timezone-aware"):
            require_utc("stamp", datetime(2026, 1, 5, 9))

    def test_rejects_non_utc_offsets(self) -> None:
        with pytest.raises(TimezoneError, match="in UTC"):
            require_utc("stamp", datetime(2026, 1, 5, 9, tzinfo=TEHRAN))

    def test_rejects_non_datetimes(self) -> None:
        with pytest.raises(TimezoneError, match="timezone-aware"):
            require_utc("stamp", "2026-01-05")  # type: ignore[arg-type]

    def test_caller_supplies_the_error_class(self) -> None:
        with pytest.raises(CustomError):
            require_utc("stamp", datetime(2026, 1, 5, 9), error=CustomError)


class TestToUtc:
    def test_normalizes_aware_instants_to_utc(self) -> None:
        # Tehran is UTC+3:30 — 14:00 local is 10:30 UTC.
        result = to_utc(datetime(2026, 1, 5, 14, tzinfo=TEHRAN))
        assert result == datetime(2026, 1, 5, 10, 30, tzinfo=UTC)
        assert result.tzinfo is UTC

    def test_utc_input_is_unchanged(self) -> None:
        instant = datetime(2026, 1, 5, 9, tzinfo=UTC)
        assert to_utc(instant) == instant

    def test_rejects_naive_datetimes(self) -> None:
        with pytest.raises(TimezoneError):
            to_utc(datetime(2026, 1, 5, 9))

    def test_caller_supplies_the_error_class(self) -> None:
        with pytest.raises(CustomError):
            to_utc(datetime(2026, 1, 5, 9), error=CustomError)


class TestLocalTime:
    def test_renders_wall_clock_time(self) -> None:
        # London winter is UTC+0; summer (BST) is UTC+1.
        winter = local_time(datetime(2026, 1, 5, 9, tzinfo=UTC), LONDON)
        assert (winter.hour, winter.tzinfo) == (9, LONDON)
        summer = local_time(datetime(2026, 6, 1, 9, tzinfo=UTC), LONDON)
        assert (summer.hour, summer.tzinfo) == (10, LONDON)

    def test_rejects_naive_instants_and_bad_zones(self) -> None:
        with pytest.raises(TimezoneError):
            local_time(datetime(2026, 1, 5, 9), LONDON)  # type: ignore[arg-type]
        with pytest.raises(TimezoneError):
            local_time(datetime(2026, 1, 5, 9, tzinfo=UTC), "Europe/London")  # type: ignore[arg-type]


class TestInstantFromWallClock:
    def test_builds_utc_instant(self) -> None:
        assert instant_from_wall_clock(
            date(2026, 1, 5), time(9, 0), LONDON
        ) == datetime(2026, 1, 5, 9, tzinfo=UTC)

    def test_shifts_across_dst_transitions(self) -> None:
        # London springs forward on 2026-03-29: 9:00 local is 09:00 UTC
        # the Monday before and 08:00 UTC the Monday after.
        before = instant_from_wall_clock(date(2026, 3, 23), time(9, 0), LONDON)
        after = instant_from_wall_clock(date(2026, 3, 30), time(9, 0), LONDON)
        assert before == datetime(2026, 3, 23, 9, tzinfo=UTC)
        assert after == datetime(2026, 3, 30, 8, tzinfo=UTC)

    def test_fold_selects_ambiguous_occurrence(self) -> None:
        # London falls back on 2026-10-25: 01:30 local occurs twice.
        first = instant_from_wall_clock(date(2026, 10, 25), time(1, 30), LONDON)
        second = instant_from_wall_clock(
            date(2026, 10, 25), time(1, 30), LONDON, fold=1
        )
        assert first == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
        assert second == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)

    def test_rejects_bad_inputs(self) -> None:
        with pytest.raises(TimezoneError):
            instant_from_wall_clock("2026-01-05", time(9), LONDON)  # type: ignore[arg-type]
        with pytest.raises(TimezoneError):
            instant_from_wall_clock(date(2026, 1, 5), time(9, tzinfo=UTC), LONDON)
        with pytest.raises(TimezoneError):
            instant_from_wall_clock(date(2026, 1, 5), time(9), "Europe/London")  # type: ignore[arg-type]


class TestLocalTimeKind:
    def test_normal_times_are_unambiguous(self) -> None:
        assert (
            local_time_kind(date(2026, 1, 5), time(9, 0), LONDON)
            is LocalTimeKind.UNAMBIGUOUS
        )

    def test_spring_forward_times_are_nonexistent(self) -> None:
        # London springs forward 2026-03-29 01:00 → 02:00: 01:30 never
        # happens.
        assert (
            local_time_kind(date(2026, 3, 29), time(1, 30), LONDON)
            is LocalTimeKind.NONEXISTENT
        )

    def test_fall_back_times_are_ambiguous(self) -> None:
        # London falls back 2026-10-25 02:00 → 01:00: 01:30 happens
        # twice.
        assert (
            local_time_kind(date(2026, 10, 25), time(1, 30), LONDON)
            is LocalTimeKind.AMBIGUOUS
        )

    def test_zones_without_dst_are_always_unambiguous(self) -> None:
        assert (
            local_time_kind(date(2026, 3, 29), time(1, 30), TEHRAN)
            is LocalTimeKind.UNAMBIGUOUS
        )

    def test_rejects_bad_inputs(self) -> None:
        with pytest.raises(TimezoneError):
            local_time_kind(date(2026, 1, 5), time(9, tzinfo=UTC), LONDON)


class TestWeekBounds:
    def test_week_is_monday_anchored_in_local_zone(self) -> None:
        # Thursday 2026-01-08 in Tehran: the containing week runs Mon
        # 2026-01-05 00:00 (+03:30) → Mon 2026-01-12 00:00 (+03:30).
        instant = datetime(2026, 1, 8, 12, tzinfo=UTC)
        start, end = week_bounds(instant, TEHRAN)
        assert start == datetime(2026, 1, 4, 20, 30, tzinfo=UTC)
        assert end == datetime(2026, 1, 11, 20, 30, tzinfo=UTC)

    def test_sunday_belongs_to_the_prior_week(self) -> None:
        # Sunday 2026-01-11 is the last day of the week starting Mon
        # 2026-01-05.
        instant = datetime(2026, 1, 11, 23, tzinfo=UTC)
        start, end = week_bounds(instant, LONDON)
        assert start == datetime(2026, 1, 5, 0, tzinfo=UTC)
        assert end == datetime(2026, 1, 12, 0, tzinfo=UTC)

    def test_dst_week_is_167_hours(self) -> None:
        # The London week Mon 2026-03-23 → Mon 2026-03-30 spans the
        # spring-forward: 6 days 23 hours.
        instant = datetime(2026, 3, 25, 12, tzinfo=UTC)
        start, end = week_bounds(instant, LONDON)
        assert start == datetime(2026, 3, 23, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 29, 23, tzinfo=UTC)
        assert end - start == timedelta(weeks=1) - timedelta(hours=1)

    def test_rejects_bad_inputs(self) -> None:
        with pytest.raises(TimezoneError):
            week_bounds(datetime(2026, 1, 8), LONDON)  # type: ignore[arg-type]
        with pytest.raises(TimezoneError):
            week_bounds(datetime(2026, 1, 8, tzinfo=UTC), "Europe/London")  # type: ignore[arg-type]
