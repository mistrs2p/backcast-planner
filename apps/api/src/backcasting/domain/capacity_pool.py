"""Capacity pool domain model.

A user pursues several goals at once, so the usable capacity of a
period must be split among them. A Capacity Pool is that split: the
effective capacity of a period (TASK-040) plus one allocation per
goal.

Rules:

- IDs are UUIDs; ``capacity_id`` references the effective-capacity
  record being split; each allocation names a goal and a non-negative
  amount.
- Allocations are a non-empty tuple with unique goal ids — a goal
  appears at most once (merge competing amounts before allocating).
- The split never exceeds the pool: ``allocated_amount`` equals the
  sum of allocations and ``unallocated_amount`` is the non-negative
  remainder (equality means the capacity is fully committed).
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.

An allocation of zero is valid: a goal can hold a place in the pool
(the user's intent to keep it alive) without consuming capacity yet.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backcasting.domain.effective_capacity import EffectiveCapacity
from backcasting.domain.timezone import UTC, require_utc


class CapacityPoolError(ValueError):
    """Raised when a capacity-pool invariant is violated."""


@dataclass(frozen=True)
class CapacityAllocation:
    """One goal's share of a capacity pool."""

    goal_id: uuid.UUID
    amount: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.goal_id, uuid.UUID):
            raise CapacityPoolError("goal_id must be a UUID")
        if not isinstance(self.amount, timedelta) or self.amount < timedelta(0):
            raise CapacityPoolError("amount must be a non-negative timedelta")


@dataclass(frozen=True)
class CapacityPool:
    """The split of a period's effective capacity across goals."""

    pool_id: uuid.UUID
    calendar_id: uuid.UUID
    capacity_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    effective_amount: timedelta
    allocations: tuple[CapacityAllocation, ...]
    allocated_amount: timedelta
    unallocated_amount: timedelta
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.pool_id, uuid.UUID):
            raise CapacityPoolError("pool_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise CapacityPoolError("calendar_id must be a UUID")
        if not isinstance(self.capacity_id, uuid.UUID):
            raise CapacityPoolError("capacity_id must be a UUID")
        require_utc("period_start", self.period_start, error=CapacityPoolError)
        require_utc("period_end", self.period_end, error=CapacityPoolError)
        if self.period_end <= self.period_start:
            raise CapacityPoolError("period_end must be after period_start")
        if (
            not isinstance(self.effective_amount, timedelta)
            or self.effective_amount < timedelta(0)
        ):
            raise CapacityPoolError(
                "effective_amount must be a non-negative timedelta"
            )
        if not isinstance(self.allocations, tuple) or not self.allocations:
            raise CapacityPoolError(
                "allocations must be a non-empty tuple of CapacityAllocation"
            )
        seen_goals: set[uuid.UUID] = set()
        for allocation in self.allocations:
            if not isinstance(allocation, CapacityAllocation):
                raise CapacityPoolError(
                    "allocations must be CapacityAllocation instances"
                )
            if allocation.goal_id in seen_goals:
                raise CapacityPoolError(
                    "a goal may appear at most once in a pool"
                )
            seen_goals.add(allocation.goal_id)
        if not isinstance(self.allocated_amount, timedelta):
            raise CapacityPoolError("allocated_amount must be a timedelta")
        if self.allocated_amount != sum(
            (a.amount for a in self.allocations), timedelta(0)
        ):
            raise CapacityPoolError(
                "allocated_amount must equal the sum of allocations"
            )
        if not isinstance(self.unallocated_amount, timedelta):
            raise CapacityPoolError("unallocated_amount must be a timedelta")
        if self.unallocated_amount != self.effective_amount - self.allocated_amount:
            raise CapacityPoolError(
                "unallocated_amount must be the remainder of the capacity"
            )
        if self.unallocated_amount < timedelta(0):
            raise CapacityPoolError("allocations must not exceed the capacity")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise CapacityPoolError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise CapacityPoolError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise CapacityPoolError("updated_at must not precede created_at")

    def allocation_for(self, goal_id: uuid.UUID) -> timedelta:
        """The goal's allocation, or zero when it holds none."""
        for allocation in self.allocations:
            if allocation.goal_id == goal_id:
                return allocation.amount
        return timedelta(0)


def allocate_capacity(
    effective: EffectiveCapacity,
    allocations: tuple[CapacityAllocation, ...],
    *,
    pool_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> CapacityPool:
    """Split ``effective``'s capacity across goals.

    The allocations must be non-empty with unique goal ids and must
    not exceed the effective amount; the remainder stays unallocated
    (free capacity the scheduler may still commit).
    """
    if not isinstance(effective, EffectiveCapacity):
        raise TypeError("effective must be an EffectiveCapacity")

    allocated = sum((a.amount for a in allocations), timedelta(0))
    if allocated > effective.amount:
        raise CapacityPoolError(
            "allocations must not exceed the effective capacity"
        )

    now = created_at if created_at is not None else datetime.now(UTC)
    return CapacityPool(
        pool_id=pool_id if pool_id is not None else uuid.uuid4(),
        calendar_id=effective.calendar_id,
        capacity_id=effective.capacity_id,
        period_start=effective.period_start,
        period_end=effective.period_end,
        effective_amount=effective.amount,
        allocations=allocations,
        allocated_amount=allocated,
        unallocated_amount=effective.amount - allocated,
        created_at=now,
        updated_at=now,
    )
