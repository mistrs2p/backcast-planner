"""Tests for the capacity pool (TASK-041).

Pins the split of effective capacity across goals: unique goals,
non-negative amounts, never exceeding the pool, with the remainder
left unallocated for the scheduler.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.capacity_pool import (
    CapacityAllocation,
    CapacityPool,
    CapacityPoolError,
    allocate_capacity,
)
from backcasting.domain.effective_capacity import EffectiveCapacity

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc
HOUR = timedelta(hours=1)

TARGET_START = datetime(2026, 6, 8, tzinfo=UTC)
TARGET_END = datetime(2026, 6, 15, tzinfo=UTC)


def _effective(calendar_id=None, hours=20) -> EffectiveCapacity:
    return EffectiveCapacity(
        capacity_id=uuid.uuid4(),
        calendar_id=calendar_id or uuid.uuid4(),
        period_start=TARGET_START,
        period_end=TARGET_END,
        amount=timedelta(hours=hours),
        planned_amount=timedelta(hours=hours),
        observed_amount=timedelta(0),
        sample_count=0,
        created_at=CREATED,
        updated_at=CREATED,
    )


def _alloc(*hours: int) -> tuple[CapacityAllocation, ...]:
    return tuple(
        CapacityAllocation(goal_id=uuid.uuid4(), amount=timedelta(hours=h))
        for h in hours
    )


class TestCapacityAllocation:
    def test_valid_allocation_is_accepted(self) -> None:
        allocation = CapacityAllocation(uuid.uuid4(), timedelta(hours=5))
        assert allocation.amount == timedelta(hours=5)

    def test_non_uuid_goal_is_rejected(self) -> None:
        with pytest.raises(CapacityPoolError, match="goal_id must be a UUID"):
            CapacityAllocation("goal", HOUR)

    def test_negative_amount_is_rejected(self) -> None:
        with pytest.raises(CapacityPoolError, match="non-negative"):
            CapacityAllocation(uuid.uuid4(), -HOUR)

    def test_zero_amount_is_allowed(self) -> None:
        allocation = CapacityAllocation(uuid.uuid4(), timedelta(0))
        assert allocation.amount == timedelta(0)


class TestCapacityPoolModel:
    def _valid_kwargs(self) -> dict:
        allocations = _alloc(8, 7)
        return {
            "pool_id": uuid.uuid4(),
            "calendar_id": uuid.uuid4(),
            "capacity_id": uuid.uuid4(),
            "period_start": TARGET_START,
            "period_end": TARGET_END,
            "effective_amount": timedelta(hours=20),
            "allocations": allocations,
            "allocated_amount": timedelta(hours=15),
            "unallocated_amount": timedelta(hours=5),
            "created_at": CREATED,
            "updated_at": CREATED,
        }

    def test_valid_pool_is_accepted(self) -> None:
        pool = CapacityPool(**self._valid_kwargs())
        assert len(pool.allocations) == 2
        assert pool.unallocated_amount == timedelta(hours=5)

    def test_non_uuid_ids_are_rejected(self) -> None:
        for name in ("pool_id", "calendar_id", "capacity_id"):
            kwargs = self._valid_kwargs()
            kwargs[name] = "not-a-uuid"
            with pytest.raises(CapacityPoolError, match=f"{name} must be a UUID"):
                CapacityPool(**kwargs)

    def test_empty_allocations_are_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["allocations"] = ()
        kwargs["allocated_amount"] = timedelta(0)
        kwargs["unallocated_amount"] = timedelta(hours=20)
        with pytest.raises(CapacityPoolError, match="non-empty"):
            CapacityPool(**kwargs)

    def test_duplicate_goals_are_rejected(self) -> None:
        goal_id = uuid.uuid4()
        kwargs = self._valid_kwargs()
        kwargs["allocations"] = (
            CapacityAllocation(goal_id, HOUR),
            CapacityAllocation(goal_id, HOUR),
        )
        kwargs["allocated_amount"] = 2 * HOUR
        kwargs["unallocated_amount"] = timedelta(hours=18)
        with pytest.raises(CapacityPoolError, match="at most once"):
            CapacityPool(**kwargs)

    def test_allocated_amount_must_match_allocations(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["allocated_amount"] = timedelta(hours=14)
        with pytest.raises(CapacityPoolError, match="sum of allocations"):
            CapacityPool(**kwargs)

    def test_unallocated_amount_must_be_the_remainder(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["unallocated_amount"] = timedelta(hours=4)
        with pytest.raises(CapacityPoolError, match="remainder"):
            CapacityPool(**kwargs)

    def test_over_allocation_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["allocations"] = _alloc(15, 6)
        kwargs["allocated_amount"] = timedelta(hours=21)
        kwargs["unallocated_amount"] = -HOUR
        with pytest.raises(CapacityPoolError, match="must not exceed"):
            CapacityPool(**kwargs)

    def test_inverted_period_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["period_end"] = kwargs["period_start"]
        with pytest.raises(CapacityPoolError, match="after period_start"):
            CapacityPool(**kwargs)

    def test_stamps_must_be_utc_and_ordered(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["updated_at"] = CREATED - timedelta(seconds=1)
        with pytest.raises(CapacityPoolError, match="must not precede"):
            CapacityPool(**kwargs)

    def test_allocation_for_lookup(self) -> None:
        goal_id = uuid.uuid4()
        pool = CapacityPool(
            **{
                **self._valid_kwargs(),
                "allocations": (
                    CapacityAllocation(goal_id, timedelta(hours=8)),
                    CapacityAllocation(uuid.uuid4(), timedelta(hours=7)),
                ),
            }
        )
        assert pool.allocation_for(goal_id) == timedelta(hours=8)
        assert pool.allocation_for(uuid.uuid4()) == timedelta(0)


class TestAllocateCapacity:
    def test_splits_effective_capacity(self) -> None:
        effective = _effective(hours=20)
        allocations = _alloc(8, 7)
        pool = allocate_capacity(effective, allocations)
        assert pool.allocated_amount == timedelta(hours=15)
        assert pool.unallocated_amount == timedelta(hours=5)
        assert pool.effective_amount == timedelta(hours=20)

    def test_full_allocation_leaves_no_remainder(self) -> None:
        effective = _effective(hours=20)
        pool = allocate_capacity(effective, _alloc(12, 8))
        assert pool.unallocated_amount == timedelta(0)
        assert pool.allocated_amount == effective.amount

    def test_zero_allocations_hold_a_place(self) -> None:
        effective = _effective(hours=20)
        pool = allocate_capacity(
            effective,
            (CapacityAllocation(uuid.uuid4(), timedelta(0)),),
        )
        assert pool.allocated_amount == timedelta(0)
        assert pool.unallocated_amount == timedelta(hours=20)

    def test_over_allocation_is_rejected(self) -> None:
        effective = _effective(hours=20)
        with pytest.raises(CapacityPoolError, match="must not exceed"):
            allocate_capacity(effective, _alloc(15, 6))

    def test_rejects_non_effective(self) -> None:
        with pytest.raises(TypeError, match="effective must be"):
            allocate_capacity("effective", _alloc(1))

    def test_empty_allocations_are_rejected(self) -> None:
        with pytest.raises(CapacityPoolError, match="non-empty"):
            allocate_capacity(_effective(), ())

    def test_binds_the_effective_record(self) -> None:
        effective = _effective(hours=10)
        pool = allocate_capacity(effective, _alloc(10))
        assert pool.capacity_id == effective.capacity_id
        assert pool.calendar_id == effective.calendar_id
        assert pool.period_start == effective.period_start
        assert pool.period_end == effective.period_end

    def test_injectable_id_and_clock(self) -> None:
        pool_id = uuid.uuid4()
        pool = allocate_capacity(
            _effective(hours=10),
            _alloc(10),
            pool_id=pool_id,
            created_at=CREATED,
        )
        assert pool.pool_id == pool_id
        assert pool.created_at == CREATED
        assert pool.updated_at == CREATED

    def test_generated_id_is_unique(self) -> None:
        first = allocate_capacity(_effective(hours=10), _alloc(10))
        second = allocate_capacity(_effective(hours=10), _alloc(10))
        assert first.pool_id != second.pool_id
