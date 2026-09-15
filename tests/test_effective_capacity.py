"""Tests for effective capacity (TASK-040).

Pins the usable-capacity computation the feasibility rule trusts
(docs/04 step 7): the plan adjusted by the observed/planned ratio of
history, with the cold-start and zero-plan fallbacks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.effective_capacity import (
    CapacitySample,
    EffectiveCapacity,
    EffectiveCapacityError,
    compute_effective_capacity,
)
from backcasting.domain.observed_capacity import ObservedCapacity
from backcasting.domain.planned_capacity import PlannedCapacity

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc
HOUR = timedelta(hours=1)

# Target period: the upcoming week.
TARGET_START = datetime(2026, 6, 8, tzinfo=UTC)
TARGET_END = datetime(2026, 6, 15, tzinfo=UTC)

# Past weeks for history.
WEEK1_START = datetime(2026, 6, 1, tzinfo=UTC)
WEEK1_END = datetime(2026, 6, 8, tzinfo=UTC)
WEEK2_START = datetime(2026, 5, 25, tzinfo=UTC)
WEEK2_END = datetime(2026, 6, 1, tzinfo=UTC)


def _planned(calendar_id, start, end, hours, **overrides) -> PlannedCapacity:
    kwargs = {
        "capacity_id": uuid.uuid4(),
        "calendar_id": calendar_id,
        "period_start": start,
        "period_end": end,
        "amount": timedelta(hours=hours),
        "created_at": CREATED,
        "updated_at": CREATED,
    }
    kwargs.update(overrides)
    return PlannedCapacity(**kwargs)


def _observed(calendar_id, start, end, hours, **overrides) -> ObservedCapacity:
    kwargs = {
        "capacity_id": uuid.uuid4(),
        "calendar_id": calendar_id,
        "period_start": start,
        "period_end": end,
        "amount": timedelta(hours=hours),
        "measured_at": end + timedelta(days=1),
    }
    kwargs.update(overrides)
    return ObservedCapacity(**kwargs)


def _target_planned(calendar_id, hours=20) -> PlannedCapacity:
    return _planned(calendar_id, TARGET_START, TARGET_END, hours)


class TestCapacitySample:
    def test_pairs_records_of_the_same_period(self) -> None:
        calendar_id = uuid.uuid4()
        sample = CapacitySample(
            planned=_planned(calendar_id, WEEK1_START, WEEK1_END, 20),
            observed=_observed(calendar_id, WEEK1_START, WEEK1_END, 15),
        )
        assert sample.planned.amount == timedelta(hours=20)
        assert sample.observed.amount == timedelta(hours=15)

    def test_rejects_different_calendars(self) -> None:
        with pytest.raises(EffectiveCapacityError, match="different calendars"):
            CapacitySample(
                planned=_planned(uuid.uuid4(), WEEK1_START, WEEK1_END, 20),
                observed=_observed(uuid.uuid4(), WEEK1_START, WEEK1_END, 15),
            )

    def test_rejects_different_periods(self) -> None:
        calendar_id = uuid.uuid4()
        with pytest.raises(EffectiveCapacityError, match="same period"):
            CapacitySample(
                planned=_planned(calendar_id, WEEK1_START, WEEK1_END, 20),
                observed=_observed(calendar_id, WEEK2_START, WEEK2_END, 15),
            )

    def test_rejects_non_records(self) -> None:
        calendar_id = uuid.uuid4()
        with pytest.raises(EffectiveCapacityError, match="planned must be"):
            CapacitySample(
                planned="planned",
                observed=_observed(calendar_id, WEEK1_START, WEEK1_END, 15),
            )


class TestEffectiveCapacityModel:
    def _valid_kwargs(self) -> dict:
        return {
            "capacity_id": uuid.uuid4(),
            "calendar_id": uuid.uuid4(),
            "period_start": TARGET_START,
            "period_end": TARGET_END,
            "amount": timedelta(hours=15),
            "planned_amount": timedelta(hours=20),
            "observed_amount": timedelta(hours=30),
            "sample_count": 2,
            "created_at": CREATED,
            "updated_at": CREATED,
        }

    def test_valid_capacity_is_accepted(self) -> None:
        capacity = EffectiveCapacity(**self._valid_kwargs())
        assert capacity.amount == timedelta(hours=15)
        assert capacity.sample_count == 2

    def test_non_uuid_ids_are_rejected(self) -> None:
        for name in ("capacity_id", "calendar_id"):
            kwargs = self._valid_kwargs()
            kwargs[name] = "not-a-uuid"
            with pytest.raises(EffectiveCapacityError, match=f"{name} must be a UUID"):
                EffectiveCapacity(**kwargs)

    def test_inverted_period_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["period_end"] = kwargs["period_start"]
        with pytest.raises(EffectiveCapacityError, match="after period_start"):
            EffectiveCapacity(**kwargs)

    def test_negative_amounts_are_rejected(self) -> None:
        for name in ("amount", "planned_amount", "observed_amount"):
            kwargs = self._valid_kwargs()
            kwargs[name] = -HOUR
            with pytest.raises(EffectiveCapacityError, match="non-negative"):
                EffectiveCapacity(**kwargs)

    def test_negative_sample_count_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["sample_count"] = -1
        with pytest.raises(EffectiveCapacityError, match="negative"):
            EffectiveCapacity(**kwargs)

    def test_bool_sample_count_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["sample_count"] = True
        with pytest.raises(EffectiveCapacityError, match="integer"):
            EffectiveCapacity(**kwargs)

    def test_stamps_must_be_utc_and_ordered(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["updated_at"] = CREATED - timedelta(seconds=1)
        with pytest.raises(EffectiveCapacityError, match="must not precede"):
            EffectiveCapacity(**kwargs)


class TestComputeArgumentValidation:
    def test_rejects_non_planned(self) -> None:
        with pytest.raises(TypeError, match="planned must be a PlannedCapacity"):
            compute_effective_capacity("planned", ())

    def test_rejects_non_tuple_history(self) -> None:
        with pytest.raises(EffectiveCapacityError, match="history must be a tuple"):
            compute_effective_capacity(_target_planned(uuid.uuid4()), [])

    def test_rejects_non_sample_members(self) -> None:
        with pytest.raises(EffectiveCapacityError, match="CapacitySample"):
            compute_effective_capacity(_target_planned(uuid.uuid4()), ("sample",))

    def test_rejects_sample_from_other_calendar(self) -> None:
        calendar_id = uuid.uuid4()
        other_id = uuid.uuid4()
        sample = CapacitySample(
            planned=_planned(other_id, WEEK1_START, WEEK1_END, 20),
            observed=_observed(other_id, WEEK1_START, WEEK1_END, 15),
        )
        with pytest.raises(EffectiveCapacityError, match="does not belong"):
            compute_effective_capacity(_target_planned(calendar_id), (sample,))


class TestComputeAmount:
    def test_cold_start_trusts_the_plan(self) -> None:
        calendar_id = uuid.uuid4()
        capacity = compute_effective_capacity(_target_planned(calendar_id), ())
        assert capacity.amount == timedelta(hours=20)
        assert capacity.sample_count == 0
        assert capacity.observed_amount == timedelta(0)
        assert capacity.planned_amount == timedelta(hours=20)

    def test_history_scales_the_plan_down(self) -> None:
        calendar_id = uuid.uuid4()
        sample = CapacitySample(
            planned=_planned(calendar_id, WEEK1_START, WEEK1_END, 20),
            observed=_observed(calendar_id, WEEK1_START, WEEK1_END, 15),
        )
        capacity = compute_effective_capacity(
            _target_planned(calendar_id), (sample,)
        )
        assert capacity.amount == timedelta(hours=15)

    def test_history_scales_the_plan_up(self) -> None:
        calendar_id = uuid.uuid4()
        sample = CapacitySample(
            planned=_planned(calendar_id, WEEK1_START, WEEK1_END, 10),
            observed=_observed(calendar_id, WEEK1_START, WEEK1_END, 15),
        )
        capacity = compute_effective_capacity(
            _target_planned(calendar_id, hours=20), (sample,)
        )
        assert capacity.amount == timedelta(hours=30)

    def test_multiple_samples_aggregate(self) -> None:
        calendar_id = uuid.uuid4()
        history = (
            CapacitySample(
                planned=_planned(calendar_id, WEEK2_START, WEEK2_END, 20),
                observed=_observed(calendar_id, WEEK2_START, WEEK2_END, 15),
            ),
            CapacitySample(
                planned=_planned(calendar_id, WEEK1_START, WEEK1_END, 20),
                observed=_observed(calendar_id, WEEK1_START, WEEK1_END, 25),
            ),
        )
        capacity = compute_effective_capacity(
            _target_planned(calendar_id), history
        )
        # total observed 40 / total planned 40 = 1.0
        assert capacity.amount == timedelta(hours=20)
        assert capacity.observed_amount == timedelta(hours=40)
        assert capacity.sample_count == 2

    def test_zero_total_planned_history_falls_back_to_plan(self) -> None:
        calendar_id = uuid.uuid4()
        history = (
            CapacitySample(
                planned=_planned(calendar_id, WEEK1_START, WEEK1_END, 0),
                observed=_observed(calendar_id, WEEK1_START, WEEK1_END, 15),
            ),
        )
        capacity = compute_effective_capacity(
            _target_planned(calendar_id), history
        )
        assert capacity.amount == timedelta(hours=20)
        assert capacity.sample_count == 1

    def test_feeds_the_feasibility_rule(self) -> None:
        from backcasting.domain.feasibility import evaluate_feasibility

        calendar_id = uuid.uuid4()
        sample = CapacitySample(
            planned=_planned(calendar_id, WEEK1_START, WEEK1_END, 20),
            observed=_observed(calendar_id, WEEK1_START, WEEK1_END, 10),
        )
        capacity = compute_effective_capacity(
            _target_planned(calendar_id), (sample,)
        )
        # 20h workload no longer fits the effective 10h
        result = evaluate_feasibility(
            required_workload=timedelta(hours=20),
            buffer=timedelta(0),
            usable_capacity=capacity.amount,
        )
        assert result.feasible is False
        assert result.slack == -timedelta(hours=10)


class TestComputeRecord:
    def test_binds_the_planned_period(self) -> None:
        calendar_id = uuid.uuid4()
        capacity = compute_effective_capacity(_target_planned(calendar_id), ())
        assert capacity.calendar_id == calendar_id
        assert capacity.period_start == TARGET_START
        assert capacity.period_end == TARGET_END

    def test_injectable_id_and_clock(self) -> None:
        calendar_id = uuid.uuid4()
        capacity_id = uuid.uuid4()
        capacity = compute_effective_capacity(
            _target_planned(calendar_id),
            (),
            capacity_id=capacity_id,
            created_at=CREATED,
        )
        assert capacity.capacity_id == capacity_id
        assert capacity.created_at == CREATED
        assert capacity.updated_at == CREATED

    def test_generated_id_is_unique(self) -> None:
        calendar_id = uuid.uuid4()
        first = compute_effective_capacity(_target_planned(calendar_id), ())
        second = compute_effective_capacity(_target_planned(calendar_id), ())
        assert first.capacity_id != second.capacity_id
