"""Tests for observed capacity (TASK-039).

Pins the backward-looking capacity measurement: the shared workable-
time semantics run over a period that has happened, the
measured-after-the-period invariant, and the planned/observed contrast
that makes capacity variance (docs/07) meaningful.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from backcasting.domain.availability import create_availability_window
from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.calendar_event import create_event
from backcasting.domain.observed_capacity import (
    ObservedCapacity,
    ObservedCapacityError,
    measure_observed_capacity,
)
from backcasting.domain.planned_capacity import derive_planned_capacity

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc

# A past week: Monday 2026-05-25 through Sunday 2026-05-31.
PERIOD_START = datetime(2026, 5, 25, tzinfo=UTC)
PERIOD_END = datetime(2026, 6, 1, tzinfo=UTC)
MEASURED_AT = datetime(2026, 6, 2, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.fixture
def calendar() -> Calendar:
    return create_calendar(uuid.uuid4(), created_at=CREATED)


def _window(calendar: Calendar, weekdays, start: time, end: time):
    return create_availability_window(
        calendar, weekdays, start, end, created_at=CREATED
    )


def _event(calendar: Calendar, day: int, start: int, end: int):
    return create_event(
        calendar,
        "Commitment",
        datetime(2026, 5, day, start, tzinfo=UTC),
        datetime(2026, 5, day, end, tzinfo=UTC),
        created_at=CREATED,
    )


class TestObservedCapacityModel:
    def _valid_kwargs(self, calendar: Calendar) -> dict:
        return {
            "capacity_id": uuid.uuid4(),
            "calendar_id": calendar.calendar_id,
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
            "amount": timedelta(hours=12),
            "measured_at": MEASURED_AT,
        }

    def test_valid_measurement_is_accepted(self, calendar: Calendar) -> None:
        capacity = ObservedCapacity(**self._valid_kwargs(calendar))
        assert capacity.amount == timedelta(hours=12)
        assert capacity.measured_at == MEASURED_AT

    def test_non_uuid_ids_are_rejected(self, calendar: Calendar) -> None:
        for name in ("capacity_id", "calendar_id"):
            kwargs = self._valid_kwargs(calendar)
            kwargs[name] = "not-a-uuid"
            with pytest.raises(ObservedCapacityError, match=f"{name} must be a UUID"):
                ObservedCapacity(**kwargs)

    def test_naive_period_bounds_are_rejected(self, calendar: Calendar) -> None:
        for name in ("period_start", "period_end"):
            kwargs = self._valid_kwargs(calendar)
            kwargs[name] = kwargs[name].replace(tzinfo=None)
            with pytest.raises(ObservedCapacityError, match="timezone-aware"):
                ObservedCapacity(**kwargs)

    def test_inverted_period_is_rejected(self, calendar: Calendar) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["period_end"] = kwargs["period_start"]
        with pytest.raises(ObservedCapacityError, match="after period_start"):
            ObservedCapacity(**kwargs)

    def test_negative_amount_is_rejected(self, calendar: Calendar) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["amount"] = -HOUR
        with pytest.raises(ObservedCapacityError, match="non-negative"):
            ObservedCapacity(**kwargs)

    def test_measuring_before_period_end_is_rejected(
        self, calendar: Calendar
    ) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["measured_at"] = PERIOD_END - timedelta(seconds=1)
        with pytest.raises(ObservedCapacityError, match="after it has ended"):
            ObservedCapacity(**kwargs)

    def test_measuring_exactly_at_period_end_is_allowed(
        self, calendar: Calendar
    ) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["measured_at"] = PERIOD_END
        assert ObservedCapacity(**kwargs).measured_at == PERIOD_END

    def test_naive_measured_at_is_rejected(self, calendar: Calendar) -> None:
        kwargs = self._valid_kwargs(calendar)
        kwargs["measured_at"] = MEASURED_AT.replace(tzinfo=None)
        with pytest.raises(ObservedCapacityError, match="timezone-aware"):
            ObservedCapacity(**kwargs)

    def test_measurement_is_frozen(self, calendar: Calendar) -> None:
        capacity = ObservedCapacity(**self._valid_kwargs(calendar))
        with pytest.raises(AttributeError):
            capacity.amount = timedelta(0)


class TestMeasureArgumentValidation:
    def test_rejects_non_calendar(self) -> None:
        with pytest.raises(TypeError, match="calendar must be a Calendar"):
            measure_observed_capacity(
                "calendar", (), range_start=PERIOD_START, range_end=PERIOD_END
            )

    def test_rejects_non_tuple_windows(self, calendar: Calendar) -> None:
        with pytest.raises(ObservedCapacityError, match="windows must be a tuple"):
            measure_observed_capacity(
                calendar, [], range_start=PERIOD_START, range_end=PERIOD_END
            )

    def test_rejects_window_from_other_calendar(self, calendar: Calendar) -> None:
        other = create_calendar(uuid.uuid4(), created_at=CREATED)
        window = _window(other, {0}, time(18), time(21))
        with pytest.raises(ObservedCapacityError, match="does not belong"):
            measure_observed_capacity(
                calendar, (window,), range_start=PERIOD_START, range_end=PERIOD_END
            )

    def test_rejects_event_from_other_calendar(self, calendar: Calendar) -> None:
        other = create_calendar(uuid.uuid4(), created_at=CREATED)
        event = _event(other, 25, 19, 20)
        with pytest.raises(ObservedCapacityError, match="does not belong"):
            measure_observed_capacity(
                calendar,
                (),
                (event,),
                range_start=PERIOD_START,
                range_end=PERIOD_END,
            )

    def test_rejects_naive_range(self, calendar: Calendar) -> None:
        with pytest.raises(ObservedCapacityError, match="range_start"):
            measure_observed_capacity(
                calendar,
                (),
                range_start=PERIOD_START.replace(tzinfo=None),
                range_end=PERIOD_END,
            )

    def test_rejects_inverted_range(self, calendar: Calendar) -> None:
        with pytest.raises(ObservedCapacityError, match="after range_start"):
            measure_observed_capacity(
                calendar, (), range_start=PERIOD_END, range_end=PERIOD_START
            )

    def test_rejects_measurement_before_period_end(self, calendar: Calendar) -> None:
        with pytest.raises(ObservedCapacityError, match="after it has ended"):
            measure_observed_capacity(
                calendar,
                (),
                range_start=PERIOD_START,
                range_end=PERIOD_END,
                measured_at=PERIOD_START,
            )


class TestMeasureAmount:
    def test_no_windows_means_zero(self, calendar: Calendar) -> None:
        capacity = measure_observed_capacity(
            calendar,
            (),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            measured_at=MEASURED_AT,
        )
        assert capacity.amount == timedelta(0)

    def test_availability_minus_occupying_commitments(
        self, calendar: Calendar
    ) -> None:
        window = _window(calendar, {0, 1, 2, 3, 4}, time(18), time(21))
        event = _event(calendar, 25, 19, 20)
        capacity = measure_observed_capacity(
            calendar,
            (window,),
            (event,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            measured_at=MEASURED_AT,
        )
        assert capacity.amount == 5 * 3 * HOUR - HOUR

    def test_commitment_outside_availability_consumes_nothing(
        self, calendar: Calendar
    ) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        night = _event(calendar, 25, 22, 23)
        capacity = measure_observed_capacity(
            calendar,
            (window,),
            (night,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            measured_at=MEASURED_AT,
        )
        assert capacity.amount == 3 * HOUR

    def test_overlapping_commitments_count_once(self, calendar: Calendar) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        first = _event(calendar, 25, 18, 20)
        second = _event(calendar, 25, 19, 20)
        capacity = measure_observed_capacity(
            calendar,
            (window,),
            (first, second),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            measured_at=MEASURED_AT,
        )
        assert capacity.amount == HOUR


class TestPlannedObservedContrast:
    def test_same_inputs_same_amount(self, calendar: Calendar) -> None:
        window = _window(calendar, {0, 1, 2, 3, 4}, time(18), time(21))
        event = _event(calendar, 26, 19, 20)
        planned = derive_planned_capacity(
            calendar,
            (window,),
            (event,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            created_at=CREATED,
        )
        observed = measure_observed_capacity(
            calendar,
            (window,),
            (event,),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            measured_at=MEASURED_AT,
        )
        assert planned.amount == observed.amount
        assert planned.period_start == observed.period_start
        assert planned.period_end == observed.period_end

    def test_reality_diverging_from_plan_changes_the_amount(
        self, calendar: Calendar
    ) -> None:
        window = _window(calendar, {0}, time(18), time(21))
        planned = derive_planned_capacity(
            calendar,
            (window,),
            (),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            created_at=CREATED,
        )
        # The week actually brought an unplanned two-hour meeting.
        observed = measure_observed_capacity(
            calendar,
            (window,),
            (_event(calendar, 25, 19, 21),),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            measured_at=MEASURED_AT,
        )
        assert planned.amount == 3 * HOUR
        assert observed.amount == HOUR

    def test_injectable_id_and_clock(self, calendar: Calendar) -> None:
        capacity_id = uuid.uuid4()
        capacity = measure_observed_capacity(
            calendar,
            (),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            capacity_id=capacity_id,
            measured_at=MEASURED_AT,
        )
        assert capacity.capacity_id == capacity_id
        assert capacity.measured_at == MEASURED_AT
        assert capacity.calendar_id == calendar.calendar_id

    def test_generated_id_is_unique(self, calendar: Calendar) -> None:
        first = measure_observed_capacity(
            calendar,
            (),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            measured_at=MEASURED_AT,
        )
        second = measure_observed_capacity(
            calendar,
            (),
            range_start=PERIOD_START,
            range_end=PERIOD_END,
            measured_at=MEASURED_AT,
        )
        assert first.capacity_id != second.capacity_id
