"""Tests for availability windows (TASK-034).

Pins the Availability Window concept (docs/05): weekly wall-clock
patterns on a calendar, expanding into UTC intervals over a range with
DST-aware local times and range clipping. Availability ≠ capacity
(docs/00) — capacity is computed from these windows later.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.availability import (
    AvailabilityWindow,
    AvailabilityError,
    available_intervals,
    create_availability_window,
)
from backcasting.domain.calendar import Calendar, create_calendar

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
TEHRAN = ZoneInfo("Asia/Tehran")


@pytest.fixture
def calendar() -> Calendar:
    return create_calendar(uuid.uuid4(), timezone=LONDON, created_at=CREATED)


class TestAvailabilityWindow:
    def _valid_kwargs(self) -> dict:
        return {
            "window_id": uuid.uuid4(),
            "calendar_id": uuid.uuid4(),
            "weekdays": frozenset({0, 1, 2, 3, 4}),
            "start_time": time(18, 0),
            "end_time": time(21, 0),
            "timezone": LONDON,
            "created_at": CREATED,
            "updated_at": CREATED,
        }

    def test_valid_window_is_accepted(self) -> None:
        window = AvailabilityWindow(**self._valid_kwargs())
        assert window.weekdays == frozenset({0, 1, 2, 3, 4})
        assert window.start_time == time(18, 0)
        assert window.end_time == time(21, 0)
        assert window.title == ""

    def test_empty_weekdays_are_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["weekdays"] = frozenset()
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)

    @pytest.mark.parametrize("weekday", [7, -1, "mon", True, 2.5])
    def test_invalid_weekdays_are_rejected(self, weekday: object) -> None:
        kwargs = self._valid_kwargs()
        kwargs["weekdays"] = frozenset({weekday})  # type: ignore[arg-type]
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)

    @pytest.mark.parametrize(
        "start_time,end_time",
        [
            (time(21, 0), time(18, 0)),  # reversed (crosses midnight)
            (time(18, 0), time(18, 0)),  # zero length
        ],
    )
    def test_end_must_be_after_start(
        self, start_time: object, end_time: object
    ) -> None:
        kwargs = self._valid_kwargs()
        kwargs["start_time"] = start_time
        kwargs["end_time"] = end_time
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)

    @pytest.mark.parametrize("time_name", ["start_time", "end_time"])
    def test_times_must_be_naive(self, time_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[time_name] = time(18, 0, tzinfo=UTC)
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)

    @pytest.mark.parametrize("time_name", ["start_time", "end_time"])
    def test_times_must_be_time_objects(self, time_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[time_name] = "18:00"
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)

    def test_timezone_must_be_zoneinfo(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["timezone"] = "Europe/London"
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)

    def test_title_is_optional_and_bounded(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["title"] = "Evening deep work"
        assert AvailabilityWindow(**kwargs).title == "Evening deep work"
        kwargs["title"] = "x" * 201
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)

    @pytest.mark.parametrize("field_name", ["window_id", "calendar_id"])
    def test_ids_must_be_uuids(self, field_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[field_name] = "not-a-uuid"
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)

    @pytest.mark.parametrize("stamp_name", ["created_at", "updated_at"])
    def test_stamps_must_be_utc_and_aware(self, stamp_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[stamp_name] = datetime(2026, 1, 1)
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)
        kwargs[stamp_name] = CREATED.astimezone(TEHRAN)
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)

    def test_updated_at_must_not_precede_created_at(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["updated_at"] = CREATED - timedelta(seconds=1)
        with pytest.raises(AvailabilityError):
            AvailabilityWindow(**kwargs)

    def test_window_is_immutable(self) -> None:
        window = AvailabilityWindow(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            window.start_time = time(9, 0)  # type: ignore[misc]


class TestCreateAvailabilityWindow:
    def test_creates_window_bound_to_calendar(self, calendar: Calendar) -> None:
        window = create_availability_window(
            calendar,
            {0, 1, 2, 3, 4},
            time(18, 0),
            time(21, 0),
            created_at=CREATED,
        )
        assert isinstance(window.window_id, uuid.UUID)
        assert window.calendar_id == calendar.calendar_id
        assert window.timezone is LONDON  # defaults to the calendar's zone
        assert window.created_at == CREATED

    def test_created_at_defaults_to_now(self, calendar: Calendar) -> None:
        # regression: the `timezone` parameter used to shadow the
        # datetime.timezone import inside create_availability_window,
        # so the default clock crashed with AttributeError
        before = datetime.now(timezone.utc)
        window = create_availability_window(
            calendar, {0, 1, 2, 3, 4}, time(18, 0), time(21, 0)
        )
        after = datetime.now(timezone.utc)
        assert before <= window.created_at <= after

    def test_explicit_timezone_overrides_calendar(self, calendar: Calendar) -> None:
        window = create_availability_window(
            calendar,
            {0},
            time(18, 0),
            time(21, 0),
            timezone=TEHRAN,
            created_at=CREATED,
        )
        assert window.timezone is TEHRAN

    def test_injectable_id_and_clock(self, calendar: Calendar) -> None:
        window_id = uuid.uuid4()
        window = create_availability_window(
            calendar,
            {0},
            time(18, 0),
            time(21, 0),
            window_id=window_id,
            created_at=CREATED,
        )
        assert window.window_id == window_id

    def test_rejects_non_calendar(self) -> None:
        with pytest.raises(TypeError):
            create_availability_window("no", {0}, time(18), time(21))  # type: ignore[arg-type]


class TestAvailableIntervals:
    def _window(self, calendar: Calendar, weekdays={0}, tz=None) -> AvailabilityWindow:
        return create_availability_window(
            calendar,
            weekdays,
            time(18, 0),
            time(21, 0),
            timezone=tz,
            created_at=CREATED,
        )

    def test_expands_on_selected_weekdays(self, calendar: Calendar) -> None:
        # 2026-01-05 and 2026-01-12 are Mondays; window 18:00–21:00.
        window = self._window(calendar, {0})
        intervals = available_intervals(
            window,
            range_start=datetime(2026, 1, 5, tzinfo=UTC),
            range_end=datetime(2026, 1, 13, tzinfo=UTC),
        )
        assert intervals == (
            (
                datetime(2026, 1, 5, 18, tzinfo=UTC),
                datetime(2026, 1, 5, 21, tzinfo=UTC),
            ),
            (
                datetime(2026, 1, 12, 18, tzinfo=UTC),
                datetime(2026, 1, 12, 21, tzinfo=UTC),
            ),
        )

    def test_multiple_weekdays_in_chronological_order(
        self, calendar: Calendar
    ) -> None:
        # Mondays and Wednesdays; the range starts mid-week.
        window = self._window(calendar, {0, 2})
        intervals = available_intervals(
            window,
            range_start=datetime(2026, 1, 6, tzinfo=UTC),  # Tuesday
            range_end=datetime(2026, 1, 13, tzinfo=UTC),
        )
        assert [start for start, _ in intervals] == [
            datetime(2026, 1, 7, 18, tzinfo=UTC),  # Wednesday
            datetime(2026, 1, 12, 18, tzinfo=UTC),  # Monday
        ]

    def test_dst_transition_preserves_local_time(
        self, calendar: Calendar
    ) -> None:
        # London springs forward 2026-03-29: Monday 18:00 local is
        # 18:00 UTC before and 17:00 UTC after.
        window = self._window(calendar, {0})
        intervals = available_intervals(
            window,
            range_start=datetime(2026, 3, 20, tzinfo=UTC),
            range_end=datetime(2026, 4, 6, 23, tzinfo=UTC),
        )
        assert intervals == (
            (
                datetime(2026, 3, 23, 18, tzinfo=UTC),
                datetime(2026, 3, 23, 21, tzinfo=UTC),
            ),
            (
                datetime(2026, 3, 30, 17, tzinfo=UTC),
                datetime(2026, 3, 30, 20, tzinfo=UTC),
            ),
            (
                datetime(2026, 4, 6, 17, tzinfo=UTC),
                datetime(2026, 4, 6, 20, tzinfo=UTC),
            ),
        )

    def test_intervals_are_clipped_to_range(self, calendar: Calendar) -> None:
        window = self._window(calendar, {0})
        intervals = available_intervals(
            window,
            range_start=datetime(2026, 1, 5, 19, 30, tzinfo=UTC),
            range_end=datetime(2026, 1, 5, 20, tzinfo=UTC),
        )
        assert intervals == (
            (
                datetime(2026, 1, 5, 19, 30, tzinfo=UTC),
                datetime(2026, 1, 5, 20, tzinfo=UTC),
            ),
        )

    def test_range_without_matching_weekdays_is_empty(
        self, calendar: Calendar
    ) -> None:
        window = self._window(calendar, {0})  # Mondays only
        assert (
            available_intervals(
                window,
                range_start=datetime(2026, 1, 6, tzinfo=UTC),  # Tuesday
                range_end=datetime(2026, 1, 8, 23, tzinfo=UTC),  # Thursday
            )
            == ()
        )

    def test_non_utc_zone_windows_convert_to_utc(
        self, calendar: Calendar
    ) -> None:
        # Tehran is UTC+3:30 — 18:00 local is 14:30 UTC.
        window = self._window(calendar, {0}, tz=TEHRAN)
        intervals = available_intervals(
            window,
            range_start=datetime(2026, 1, 5, tzinfo=UTC),
            range_end=datetime(2026, 1, 5, 23, tzinfo=UTC),
        )
        assert intervals == (
            (
                datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
                datetime(2026, 1, 5, 17, 30, tzinfo=UTC),
            ),
        )

    @pytest.mark.parametrize(
        "range_start,range_end",
        [
            (datetime(2026, 1, 5), datetime(2026, 1, 6, tzinfo=UTC)),
            (
                datetime(2026, 1, 5, tzinfo=UTC),
                datetime(2026, 1, 6, tzinfo=TEHRAN),
            ),
            (datetime(2026, 1, 6, tzinfo=UTC), datetime(2026, 1, 5, tzinfo=UTC)),
        ],
    )
    def test_invalid_ranges_are_rejected(
        self, calendar: Calendar, range_start: object, range_end: object
    ) -> None:
        window = self._window(calendar, {0})
        with pytest.raises(AvailabilityError):
            available_intervals(
                window,
                range_start=range_start,  # type: ignore[arg-type]
                range_end=range_end,  # type: ignore[arg-type]
            )

    def test_rejects_non_window(self) -> None:
        with pytest.raises(TypeError):
            available_intervals(
                "not a window",
                range_start=datetime(2026, 1, 5, tzinfo=UTC),
                range_end=datetime(2026, 1, 6, tzinfo=UTC),
            )
