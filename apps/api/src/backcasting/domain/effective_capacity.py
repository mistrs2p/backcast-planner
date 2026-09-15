"""Effective capacity domain model.

Effective capacity is the *usable* capacity the feasibility rule
trusts: "Required Workload + Buffer ≤ usable Capacity" (docs/04,
pipeline step 7 — :func:`evaluate_feasibility`). Planned capacity is
what the user estimates; observed capacity is what history measured.
Effective capacity is what the planner should actually plan against —
the plan, adjusted by how much of it reality has been delivering.

The adjustment is the aggregate observed/planned ratio over the
history samples: planning 20h while every past week delivered 15h of
the 20h planned means trusting 15h. Deterministic rules:

- no history → effective = planned (nothing learned yet — cold start);
- zero total planned across history → the ratio is undefined, so
  effective = planned (you cannot learn a ratio from zero plans);
- otherwise effective = planned × (Σ observed / Σ planned). The
  result is *not* capped at the plan: a history of over-delivery is
  real signal too — conservatism is the buffer's job (its own task),
  not the capacity's.

A :class:`CapacitySample` pairs the planned and the observed record of
one past period; both must describe the same calendar and the same
period, or the ratio would compare unlike things.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backcasting.domain.observed_capacity import ObservedCapacity
from backcasting.domain.planned_capacity import PlannedCapacity
from backcasting.domain.timezone import UTC, require_utc


class EffectiveCapacityError(ValueError):
    """Raised when an effective-capacity invariant is violated."""


@dataclass(frozen=True)
class CapacitySample:
    """The planned and observed capacity of one past period."""

    planned: PlannedCapacity
    observed: ObservedCapacity

    def __post_init__(self) -> None:
        if not isinstance(self.planned, PlannedCapacity):
            raise EffectiveCapacityError("planned must be a PlannedCapacity")
        if not isinstance(self.observed, ObservedCapacity):
            raise EffectiveCapacityError("observed must be an ObservedCapacity")
        if self.planned.calendar_id != self.observed.calendar_id:
            raise EffectiveCapacityError(
                "sample mixes capacities of different calendars"
            )
        if (
            self.planned.period_start != self.observed.period_start
            or self.planned.period_end != self.observed.period_end
        ):
            raise EffectiveCapacityError(
                "sample planned and observed records must cover the same period"
            )


@dataclass(frozen=True)
class EffectiveCapacity:
    """The usable capacity to plan with for a period."""

    capacity_id: uuid.UUID
    calendar_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    amount: timedelta
    planned_amount: timedelta
    observed_amount: timedelta
    sample_count: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.capacity_id, uuid.UUID):
            raise EffectiveCapacityError("capacity_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise EffectiveCapacityError("calendar_id must be a UUID")
        require_utc("period_start", self.period_start, error=EffectiveCapacityError)
        require_utc("period_end", self.period_end, error=EffectiveCapacityError)
        if self.period_end <= self.period_start:
            raise EffectiveCapacityError("period_end must be after period_start")
        for amount_name in ("amount", "planned_amount", "observed_amount"):
            amount = getattr(self, amount_name)
            if not isinstance(amount, timedelta) or amount < timedelta(0):
                raise EffectiveCapacityError(
                    f"{amount_name} must be a non-negative timedelta"
                )
        if isinstance(self.sample_count, bool) or not isinstance(
            self.sample_count, int
        ):
            raise EffectiveCapacityError("sample_count must be an integer")
        if self.sample_count < 0:
            raise EffectiveCapacityError("sample_count must not be negative")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise EffectiveCapacityError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise EffectiveCapacityError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise EffectiveCapacityError("updated_at must not precede created_at")


def compute_effective_capacity(
    planned: PlannedCapacity,
    history: tuple[CapacitySample, ...],
    *,
    capacity_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> EffectiveCapacity:
    """Compute the usable capacity for ``planned``'s period.

    ``history`` pairs past periods' planned and observed capacities.
    With no history (or a history whose plans sum to zero) the plan is
    trusted as-is; otherwise it is scaled by the aggregate
    observed/planned ratio.
    """
    if not isinstance(planned, PlannedCapacity):
        raise TypeError("planned must be a PlannedCapacity")
    if not isinstance(history, tuple):
        raise EffectiveCapacityError("history must be a tuple of CapacitySample")
    for sample in history:
        if not isinstance(sample, CapacitySample):
            raise EffectiveCapacityError("history must be CapacitySample instances")
        if sample.planned.calendar_id != planned.calendar_id:
            raise EffectiveCapacityError(
                "sample does not belong to this calendar"
            )

    total_planned = timedelta(0)
    total_observed = timedelta(0)
    for sample in history:
        total_planned += sample.planned.amount
        total_observed += sample.observed.amount

    if not history or total_planned == timedelta(0):
        amount = planned.amount
    else:
        ratio = total_observed / total_planned
        amount = timedelta(seconds=planned.amount.total_seconds() * ratio)

    now = created_at if created_at is not None else datetime.now(UTC)
    return EffectiveCapacity(
        capacity_id=capacity_id if capacity_id is not None else uuid.uuid4(),
        calendar_id=planned.calendar_id,
        period_start=planned.period_start,
        period_end=planned.period_end,
        amount=amount,
        planned_amount=planned.amount,
        observed_amount=total_observed,
        sample_count=len(history),
        created_at=now,
        updated_at=now,
    )
