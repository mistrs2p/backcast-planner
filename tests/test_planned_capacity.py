"""Tests for planned capacity (TASK-038).

Pins the "Availability ≠ Capacity" computation (docs/00): availability
windows merged over a period, reduced by the commitments occupying
them — never counting a minute twice, never letting an
outside-availability commitment eat workable time.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.availability import (
    AvailabilityWindow,
    create_availability_window,
)
from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.calendar_event import create_event
from backcasting.domain.planned_capacity import (
    PlannedCapacity,
    PlannedCapacityError,
    derive_planned_capacity,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")

# The test period: Monday 2026-06-01 through Sunday 2026-06-07 (UTC).
PERIOD_START = datetime(2026, 6, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 6, 8, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.fixture
def calendar() -> Calendar:
    # UTC-anchored so window wall-clock times equal UTC times in the
    # amount tests; the DST test builds its own London calendar.
    return create_calendar(uuid.uuid4(), created_at=CREATED)


def _window(calendar: Calendar, weekdays, start: time, end: time, **overrides):
    return create_availability_window(
        calendar, weekdays, start, end, created_at=CREATED, **overrides
    )


def _event(calendar: Calendar, day: int, start: int, end: int):
    return create_event(
        calendar,
        "Commitment",
        datetime(2026, 6, day, start, tzinfo=UTC),
        datetime(2026, 6, day, end, tzinfo=UTC),
        created_at=CREATED,
    )


class TestPlannedCapacityModel:
    def _valid_kwargs(self, calendar: Calendar) -> dict:
        return {
            "capacity_id": uuid.uuid4(),
            "calendar_id": calendar.calendar_id,
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
            "amount": timedelta(hours=20),
            "created_at": CREATED,
            "updated_at": CREATED,
        }

    def test_valid_capacity_is_accepted(self, calendar: Calendar) -> None:
        capacity = PlannedCapacity(**self._valid_kwargs(calendar))
        assert capacity.amount == timedelta(hours=20)
        assert capacity.period_start == PERIOD_START

    def test_non_uuid_ids_are_rejected(self, calendar: Calendar) -> None:
        for name in ("capacity_id", "calendar_id"):
            kwargs = self._valid_kwargs(calendar)
            kwargs[name] = "not-a-uuid"
            with pytest.raises(PlannedCapacityError, match=f"{name} must be a UUID"):
                PlannedCapacity(**kwargs)

    def test_naive_period_bounds_are_rejected(self, calendar: Calendar) -> None:
        for name in ("period_start", "period_end"):
            kwargs = self._valid_kwargs(calendar)
            kwargs[name] = kwargs[name].replace(tzinfo=None)
            with pytest.raises(PlannedCapacityError, match="timezone-aware"):
                PlannedCapacity(**kwargs)

    def test_non_utc_period_bounds_are_rejected(self, calendar: Calendar) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["period_start"] = PERIOD_START.astimezone(ZoneInfo("Asia/Tehran"))
        with pytest.raises(PlannedCapacityError, match="must be in UTC"):
            PlannedCapacity(**kwargs)

    def test_inverted_period_is_rejected(self, calendar: Calendar) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["period_end"] = kwargs["period_start"]
        with pytest.raises(PlannedCapacityError, match="after period_start"):
            PlannedCapacity(**kwargs)

    def test_negative_amount_is_rejected(self, calendar: Calendar) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["amount"] = -HOUR
        with pytest.raises(PlannedCapacityError, match="non-negative"):
            PlannedCapacity(**kwargs)

    def test_non_timedelta_amount_is_rejected(self, calendar: Calendar) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["amount"] = 20
        with pytest.raises(PlannedCapacityError, match="timedelta"):
            PlannedCapacity(**kwargs)

    def test_zero_amount_is_allowed(self, calendar: Calendar) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["amount"] = timedelta(0)
        assert PlannedCapacity(**kwargs).amount == timedelta(0)

    def test_stamps_must_be_utc_and_ordered(self, calendar: Calendar) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["updated_at"] = CREATED - timedelta(seconds=1)
        with pytest.raises(PlannedCapacityError, match="must not precede"):
            PlannedCapacity(**kwargs)


class TestDeriveArgumentValidation:
    def test_rejects_non_calendar(self) -> None:
        with pytest.raises(TypeError, match="calendar must be a Calendar"):
            derive_planned_capacity(
                "calendar", (), range_start=PERIOD_START, range_end=PERIOD_END
            )

    def test_rejects_non_tuple_windows(self, calendar: Calendar) -> None:
        with pytest.raises(PlannedCapacityError, match="windows must be a tuple"):
            derive_planned_capacity(
                calendar, [], range_start=PERIOD_START, range_end=PERIOD_END
            )

    def test_rejects_non_window_members(self, calendar: Calendar) -> None:
        with pytest.raises(PlannedCapacityError, match="AvailabilityWindow"):
            derive_planned_capacity(
                calendar, ("window",), range_start=PERIOD_START, range_end=PERIOD_END
            )

    def test_rejects_window_from_other_calendar(self, calendar: Calendar) -> None:
        other = create_calendar(uuid.uuid4(), created_at=CREATED)
        window = _window(other, {0}, time(18), time(21))
        with pytest.raises(PlannedCapacityError, match="does not belong"):
            derive_planned_capacity(
                calendar, (window,), range_start=PERIOD_START, range_end=PERIOD_END
            )

    def test_rejects_non_tuple_events(self, calendar: Calendar) -> None:
        with pytest.raises(PlannedCapacityError, match="events must be a tuple"):
            derive_planned_capacity(
                calendar, (), [], range_start=PERIOD_START, range_end=PERIOD_END
            )

    def test_rejects_event_from_other_calendar(self, calendar: Calendar) -> None:
        other = create_calendar(uuid.uuid4(), created_at=CREATED)
        event = _event(other, 1, 19, 20)
        with pytest.raises(PlannedCapacityError, match="does not belong"):
            derive_planned_capacity(
                calendar, (), (event,), range_start=PERIOD_START, range_end=PERIOD_END
            )

    def test_rejects_naive_range(self, calendar: Calendar) -> None:
        with pytest.raises(PlannedCapacityError, match="range_start"):
            derive_planned_capacity(
                calendar,
                (),
                range_start=PERIOD_START.replace(tzinfo=None),
                range_end=PERIOD_END,
            )

    def test_rejects_inverted_range(self, calendar: Calendar) -> None:
        with pytest.raises(PlannedCapacityError, match="after range_start"):
            derive_planned_capacity(
                calendar, (), range_start=PERIOD_END, range_end=PERIOD_START
            )


class TestDeriveAmount:
    def test_no_windows_means_zero_capacity(self, calendar: Calendar) -> None:
        capacity = derive_planned_capacity(
            calendar, (), range_start=PERIOD_START, range_end=PERIOD_END
        )
        assert capacity.amount == timedelta(0)
        assert isinstance(capacity, PlannedCapacity)
        assert capacity.calendar_id == calendar.calendar_id

    def test_single_window_full_week(self, calendar: Calendar) -> None:
        window = _window(calendar, {0, 1, 2, 3, 4}, time(18), time(21))
        capacity = derive_planned_capacity(
            calendar, (window,), range_start=PERIOD_START, range_end=PERIOD_END
        )
        assert capacity.amount == 5 * 3 * HOUR

    def test_overlapping_windows_are_merged(self, calendar: Calendar) -> None:
        early = _window(calendar, {0}, time(18), time(21))
        late = _window(calendar, {0}, time(20), time(22))
        capacity = derive_planned_capacity(
            calendar, (early, late), range_start=PERIOD_START, range_end=PERIOD_END
        )
        assert capacity.amount == 4 * HOUR  # 18:00–22:00, counted once

    def test_touching_windows_are_merged(self, calendar: Calendar) -> None:
        first = _window(calendar, {0}, time(18), time(20))
        second = _window(calendar, {0}, time(20), time(21))
        capacity = derive_planned_capacity(
            calendar, (first, second), range_start=PERIOD_START, range_end=PERIOD_END
        )
        assert capacity.amount == 3 * HOUR

    def test_commitment_inside_availability_reduces_it(self, calendar: Calendar) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        event = _event(calendar, 1, 19, 20)
        capacity = derive_planned_capacity(
            calendar,
            (window,),
            (event,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
        )
        assert capacity.amount == 2 * HOUR

    def test_commitment_outside_availability_does_not_reduce(
        self, calendar: Calendar
    ) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        night_event = _event(calendar, 1, 22, 23)
        capacity = derive_planned_capacity(
            calendar,
            (window,),
            (night_event,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
        )
        assert capacity.amount == 3 * HOUR

    def test_commitment_spanning_window_reduces_to_zero(
        self, calendar: Calendar
    ) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        all_day = create_event(
            calendar,
            "All day",
            datetime(2026, 6, 1, tzinfo=UTC),
            datetime(2026, 6, 2, tzinfo=UTC),
            created_at=CREATED,
        )
        capacity = derive_planned_capacity(
            calendar,
            (window,),
            (all_day,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
        )
        assert capacity.amount == timedelta(0)

    def test_partially_overlapping_commitment_is_clipped(
        self, calendar: Calendar
    ) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        straddling = _event(calendar, 1, 20, 22)
        capacity = derive_planned_capacity(
            calendar,
            (window,),
            (straddling,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
        )
        assert capacity.amount == 2 * HOUR

    def test_overlapping_commitments_count_once(self, calendar: Calendar) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        first = _event(calendar, 1, 18, 20)
        second = _event(calendar, 1, 19, 20)
        capacity = derive_planned_capacity(
            calendar,
            (window,),
            (first, second),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
        )
        assert capacity.amount == HOUR

    def test_commitment_outside_range_is_ignored(self, calendar: Calendar) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        before = create_event(
            calendar,
            "Earlier week",
            datetime(2026, 5, 25, 18, tzinfo=UTC),
            datetime(2026, 5, 25, 21, tzinfo=UTC),
            created_at=CREATED,
        )
        capacity = derive_planned_capacity(
            calendar,
            (window,),
            (before,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
        )
        assert capacity.amount == 3 * HOUR

    def test_commitment_straddling_the_range_is_clipped(
        self, calendar: Calendar
    ) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        straddler = create_event(
            calendar,
            "Week boundary",
            datetime(2026, 5, 31, 18, tzinfo=UTC),   # Sunday before
            datetime(2026, 6, 1, 20, tzinfo=UTC),    # Monday inside
            created_at=CREATED,
        )
        capacity = derive_planned_capacity(
            calendar,
            (window,),
            (straddler,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
        )
        assert capacity.amount == HOUR  # 18–21 minus the clipped 18–20

    def test_windows_are_clipped_to_range(self, calendar: Calendar) -> None:
        # Availability on Sundays; the range Monday–Saturday contains
        # no Sunday, so nothing survives the clip.
        window = _window(calendar, {6}, time(10), time(12))
        capacity = derive_planned_capacity(
            calendar,
            (window,),
            range_start=PERIOD_START,
            range_end=datetime(2026, 6, 6, tzinfo=UTC),
        )
        assert capacity.amount == timedelta(0)


class TestDeriveRecord:
    def test_binds_period_and_calendar(self, calendar: Calendar) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        capacity = derive_planned_capacity(
            calendar,
            (window,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
        )
        assert capacity.calendar_id == calendar.calendar_id
        assert capacity.period_start == PERIOD_START
        assert capacity.period_end == PERIOD_END

    def test_injectable_id_and_clock(self, calendar: Calendar) -> None:
        capacity_id = uuid.uuid4()
        capacity = derive_planned_capacity(
            calendar,
            (),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            capacity_id=capacity_id,
            created_at=CREATED,
        )
        assert capacity.capacity_id == capacity_id
        assert capacity.created_at == CREATED
        assert capacity.updated_at == CREATED

    def test_generated_id_is_unique(self, calendar: Calendar) -> None:
        first = derive_planned_capacity(
            calendar, (), range_start=PERIOD_START, range_end=PERIOD_END
        )
        second = derive_planned_capacity(
            calendar, (), range_start=PERIOD_START, range_end=PERIOD_END
        )
        assert first.capacity_id != second.capacity_id


class TestDstWeek:
    def test_wall_clock_availability_across_spring_forward(self) -> None:
        # London springs forward 2026-03-29: that week is 167 hours.
        # An 18–21 window on each weekday still yields 3h/day of real
        # time — wall-clock semantics preserve the local window.
        tz_calendar = create_calendar(
            uuid.uuid4(), timezone=LONDON, created_at=CREATED
        )
        window = _window(tz_calendar, {6}, time(1), time(3))
        capacity = derive_planned_capacity(
            tz_calendar,
            (window,),
            range_start=datetime(2026, 3, 23, tzinfo=UTC),
            range_end=datetime(2026, 3, 30, tzinfo=UTC),
        )
        # Only Sunday 2026-03-29 is selected; its 01:00–03:00 local
        # window is 01:00→01:00 UTC (skip) … i.e. 2 real hours? No:
        # 01:00–03:00 local spans the 01:00 jump, so it is 1 real hour.
        assert capacity.amount == 1 * HOUR
