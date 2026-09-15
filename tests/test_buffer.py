"""Tests for the buffer (TASK-044).

Pins the conservatism layer of the feasibility rule — "Required
Workload + Buffer ≤ usable Capacity" (docs/04) — a fraction of usable
capacity deliberately held back so the plan never commits to
everything the calendar might deliver.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.buffer import (
    Buffer,
    BufferedCapacity,
    BufferError,
    apply_buffer,
    create_buffer,
    reserved_amount,
    usable_amount,
)
from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.effective_capacity import EffectiveCapacity

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")

# 2026-06-01 is a Monday.
WEEK_START = datetime(2026, 6, 1, tzinfo=UTC)
WEEK_END = WEEK_START + timedelta(days=7)
TWENTY_HOURS = timedelta(hours=20)


@pytest.fixture
def calendar() -> Calendar:
    return create_calendar(uuid.uuid4(), timezone=LONDON, created_at=CREATED)


@pytest.fixture
def effective(calendar: Calendar) -> EffectiveCapacity:
    return EffectiveCapacity(
        capacity_id=uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        period_start=WEEK_START,
        period_end=WEEK_END,
        amount=TWENTY_HOURS,
        planned_amount=TWENTY_HOURS,
        observed_amount=timedelta(hours=16),
        sample_count=1,
        created_at=CREATED,
        updated_at=CREATED,
    )


class TestBufferEntity:
    def test_valid_buffer_is_accepted(self, calendar: Calendar) -> None:
        buffer = create_buffer(
            calendar,
            0.25,
            period_start=WEEK_START,
            period_end=WEEK_END,
            created_at=CREATED,
        )
        assert buffer.calendar_id == calendar.calendar_id
        assert buffer.ratio == 0.25
        assert buffer.title == ""

    def test_zero_ratio_is_allowed(self, calendar: Calendar) -> None:
        buffer = create_buffer(
            calendar, 0, period_start=WEEK_START, period_end=WEEK_END
        )
        assert buffer.ratio == 0.0

    def test_ratio_just_below_one_is_allowed(self, calendar: Calendar) -> None:
        buffer = create_buffer(
            calendar,
            1 - 1e-9,
            period_start=WEEK_START,
            period_end=WEEK_END,
        )
        assert buffer.ratio < 1

    def test_negative_ratio_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(BufferError, match="at least 0 and less than 1"):
            create_buffer(calendar, -0.1, period_start=WEEK_START, period_end=WEEK_END)

    def test_full_ratio_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(BufferError, match="not a buffer"):
            create_buffer(calendar, 1, period_start=WEEK_START, period_end=WEEK_END)

    def test_ratio_above_one_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(BufferError, match="at least 0 and less than 1"):
            create_buffer(calendar, 1.5, period_start=WEEK_START, period_end=WEEK_END)

    def test_non_finite_ratio_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(BufferError, match="ratio must be finite"):
            create_buffer(
                calendar, float("nan"), period_start=WEEK_START, period_end=WEEK_END
            )
        with pytest.raises(BufferError, match="ratio must be finite"):
            create_buffer(
                calendar, float("inf"), period_start=WEEK_START, period_end=WEEK_END
            )

    def test_bool_ratio_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(BufferError, match="ratio must be a number"):
            create_buffer(
                calendar, True, period_start=WEEK_START, period_end=WEEK_END
            )  # type: ignore[arg-type]

    def test_inverted_period_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(BufferError, match="period_end must be after"):
            create_buffer(calendar, 0.25, period_start=WEEK_END, period_end=WEEK_START)

    def test_naive_bounds_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(BufferError, match="timezone-aware"):
            create_buffer(
                calendar,
                0.25,
                period_start=WEEK_START.replace(tzinfo=None),
                period_end=WEEK_END,
            )

    def test_non_utc_bounds_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(BufferError, match="must be in UTC"):
            create_buffer(
                calendar,
                0.25,
                period_start=WEEK_START.astimezone(LONDON),
                period_end=WEEK_END.astimezone(LONDON),
            )

    def test_non_uuid_ids_are_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(BufferError, match="buffer_id must be a UUID"):
            create_buffer(
                calendar,
                0.25,
                period_start=WEEK_START,
                period_end=WEEK_END,
                buffer_id="id",
            )

    def test_title_is_bounded(self, calendar: Calendar) -> None:
        with pytest.raises(BufferError, match="at most 200"):
            create_buffer(
                calendar,
                0.25,
                period_start=WEEK_START,
                period_end=WEEK_END,
                title="x" * 201,
            )

    def test_title_defaults_to_empty(self, calendar: Calendar) -> None:
        buffer = create_buffer(
            calendar,
            0.25,
            period_start=WEEK_START,
            period_end=WEEK_END,
            title=None,  # type: ignore[arg-type]
        )
        assert buffer.title == ""

    def test_stamps_must_be_utc_and_ordered(self, calendar: Calendar) -> None:
        buffer = create_buffer(
            calendar, 0.25, period_start=WEEK_START, period_end=WEEK_END
        )
        with pytest.raises(BufferError, match="must not precede"):
            Buffer(
                buffer_id=buffer.buffer_id,
                calendar_id=buffer.calendar_id,
                period_start=WEEK_START,
                period_end=WEEK_END,
                ratio=0.25,
                created_at=CREATED,
                updated_at=CREATED - timedelta(seconds=1),
            )


class TestReservedAndUsable:
    def _buffer(self, calendar: Calendar, ratio: float) -> Buffer:
        return create_buffer(
            calendar, ratio, period_start=WEEK_START, period_end=WEEK_END
        )

    def test_quarter_of_twenty_hours(self, calendar: Calendar) -> None:
        buffer = self._buffer(calendar, 0.25)
        assert reserved_amount(buffer, TWENTY_HOURS) == timedelta(hours=5)
        assert usable_amount(buffer, TWENTY_HOURS) == timedelta(hours=15)

    def test_zero_ratio_reserves_nothing(self, calendar: Calendar) -> None:
        buffer = self._buffer(calendar, 0)
        assert reserved_amount(buffer, TWENTY_HOURS) == timedelta(0)
        assert usable_amount(buffer, TWENTY_HOURS) == TWENTY_HOURS

    def test_zero_amount_reserves_nothing(self, calendar: Calendar) -> None:
        buffer = self._buffer(calendar, 0.5)
        assert reserved_amount(buffer, timedelta(0)) == timedelta(0)
        assert usable_amount(buffer, timedelta(0)) == timedelta(0)

    def test_reserved_plus_usable_equals_amount(self, calendar: Calendar) -> None:
        buffer = self._buffer(calendar, 0.3)
        amount = timedelta(hours=7, minutes=33)
        total = reserved_amount(buffer, amount) + usable_amount(buffer, amount)
        assert abs(total - amount) <= timedelta(microseconds=1)

    def test_ratio_near_one_never_goes_negative(self, calendar: Calendar) -> None:
        buffer = self._buffer(calendar, 1 - 1e-12)
        assert usable_amount(buffer, TWENTY_HOURS) >= timedelta(0)

    def test_negative_amount_is_rejected(self, calendar: Calendar) -> None:
        buffer = self._buffer(calendar, 0.25)
        with pytest.raises(BufferError, match="non-negative timedelta"):
            reserved_amount(buffer, -TWENTY_HOURS)
        with pytest.raises(BufferError, match="non-negative timedelta"):
            usable_amount(buffer, -TWENTY_HOURS)

    def test_non_timedelta_amount_is_rejected(self, calendar: Calendar) -> None:
        buffer = self._buffer(calendar, 0.25)
        with pytest.raises(BufferError, match="non-negative timedelta"):
            reserved_amount(buffer, 20)  # type: ignore[arg-type]

    def test_rejects_non_buffer(self) -> None:
        with pytest.raises(TypeError, match="buffer must be a Buffer"):
            reserved_amount("buffer", TWENTY_HOURS)  # type: ignore[arg-type]


class TestApplyBuffer:
    def _buffer(self, calendar: Calendar) -> Buffer:
        return create_buffer(
            calendar,
            0.25,
            period_start=WEEK_START,
            period_end=WEEK_END,
            created_at=CREATED,
        )

    def test_applies_to_matching_capacity(
        self, calendar: Calendar, effective: EffectiveCapacity
    ) -> None:
        buffered = apply_buffer(self._buffer(calendar), effective)
        assert buffered.effective is effective
        assert buffered.reserved_amount == timedelta(hours=5)
        assert buffered.usable_amount == timedelta(hours=15)

    def test_reserve_plus_usable_matches_effective(
        self, calendar: Calendar, effective: EffectiveCapacity
    ) -> None:
        buffered = apply_buffer(self._buffer(calendar), effective)
        total = buffered.reserved_amount + buffered.usable_amount
        assert abs(total - effective.amount) <= timedelta(microseconds=1)

    def test_other_calendars_buffer_is_rejected(
        self, effective: EffectiveCapacity
    ) -> None:
        other_calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        with pytest.raises(BufferError, match="does not belong to this calendar"):
            apply_buffer(self._buffer(other_calendar), effective)

    def test_other_periods_buffer_is_rejected(
        self, calendar: Calendar, effective: EffectiveCapacity
    ) -> None:
        shifted = create_buffer(
            calendar,
            0.25,
            period_start=WEEK_START + timedelta(days=7),
            period_end=WEEK_END + timedelta(days=7),
        )
        with pytest.raises(BufferError, match="same period"):
            apply_buffer(shifted, effective)

    def test_rejects_wrong_types(
        self, calendar: Calendar, effective: EffectiveCapacity
    ) -> None:
        with pytest.raises(TypeError, match="buffer must be a Buffer"):
            apply_buffer("buffer", effective)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="effective must be"):
            apply_buffer(self._buffer(calendar), "effective")  # type: ignore[arg-type]

    def test_negative_amounts_in_record_are_rejected(
        self, calendar: Calendar, effective: EffectiveCapacity
    ) -> None:
        with pytest.raises(BufferError, match="non-negative timedelta"):
            BufferedCapacity(
                effective=effective,
                buffer=self._buffer(calendar),
                reserved_amount=-timedelta(hours=1),
                usable_amount=timedelta(hours=1),
            )


class TestFactories:
    def test_rejects_non_calendar(self) -> None:
        with pytest.raises(TypeError, match="calendar must be a Calendar"):
            create_buffer(
                "calendar",  # type: ignore[arg-type]
                0.25,
                period_start=WEEK_START,
                period_end=WEEK_END,
            )

    def test_injectable_id_and_clock(self, calendar: Calendar) -> None:
        buffer_id = uuid.uuid4()
        buffer = create_buffer(
            calendar,
            0.25,
            period_start=WEEK_START,
            period_end=WEEK_END,
            buffer_id=buffer_id,
            created_at=CREATED,
        )
        assert buffer.buffer_id == buffer_id
        assert buffer.created_at == CREATED
        assert buffer.updated_at == CREATED

    def test_ratio_normalizes_to_float(self, calendar: Calendar) -> None:
        buffer = create_buffer(
            calendar, 0, period_start=WEEK_START, period_end=WEEK_END
        )
        assert isinstance(buffer.ratio, float)
        assert not isinstance(buffer.ratio, bool)
        assert math.isfinite(buffer.ratio)
