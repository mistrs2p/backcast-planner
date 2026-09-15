"""Capacity analysis — pipeline step 5, "Analyze time environment".

The deterministic aggregation the feasibility rule feeds on
(docs/04-BACKCASTING-MODEL.md, step 5). Given a calendar's time
environment — availability windows, existing commitments, hard
constraints — and the capacity history, :func:`analyze_time_environment`
composes the chain built across this epic:

- **availability** — the merged availability windows over the period
  (TASK-034 semantics: local wall-clock preserved across DST, clipped);
- **commitments** — the merged existing commitments over the period;
  only the part *occupying* availability consumes capacity (a meeting
  outside the windows consumes none of it — "Availability ≠ Capacity",
  docs/00);
- **constraints** — hard blocks (TASK-042) remove availability the way
  commitments do: time blocked by a constraint is not workable;
- **planned** — availability minus constraint blocks minus occupying
  commitments, the TASK-038 semantics extended with the constraint
  layer, because the analysis is the *whole* time environment while
  ``derive_planned_capacity`` derives the capacity record proper;
- **effective** — the plan adjusted by the aggregate observed/planned
  ratio of the history samples (TASK-040);
- **usable** — effective minus the buffer's reserve (TASK-044).

Preferences (TASK-043) are deliberately absent: they are the soft
layer that ranks candidate slots, never a quantity that reduces
capacity.

Every step reuses the shared semantics of the earlier modules; this
module only orchestrates them.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backcasting.domain.availability import AvailabilityWindow, available_intervals
from backcasting.domain.buffer import Buffer, apply_buffer
from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.constraint import Constraint, blocked_intervals
from backcasting.domain.effective_capacity import (
    CapacitySample,
    compute_effective_capacity,
)
from backcasting.domain.planned_capacity import (
    PlannedCapacity,
    _clip,
    _merge,
    _subtract,
)
from backcasting.domain.timezone import UTC, require_utc

Interval = tuple[datetime, datetime]


class CapacityAnalysisError(ValueError):
    """Raised when a capacity-analysis invariant is violated."""


@dataclass(frozen=True)
class CapacityAnalysis:
    """The analyzed time environment of a calendar over a period."""

    analysis_id: uuid.UUID
    calendar_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    availability_amount: timedelta
    commitment_amount: timedelta
    constrained_amount: timedelta
    occupying_amount: timedelta
    planned_amount: timedelta
    effective_amount: timedelta
    sample_count: int
    buffer_ratio: float
    reserved_amount: timedelta
    usable_amount: timedelta
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.analysis_id, uuid.UUID):
            raise CapacityAnalysisError("analysis_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise CapacityAnalysisError("calendar_id must be a UUID")
        require_utc("period_start", self.period_start, error=CapacityAnalysisError)
        require_utc("period_end", self.period_end, error=CapacityAnalysisError)
        if self.period_end <= self.period_start:
            raise CapacityAnalysisError("period_end must be after period_start")
        for amount_name in (
            "availability_amount",
            "commitment_amount",
            "constrained_amount",
            "occupying_amount",
            "planned_amount",
            "effective_amount",
            "reserved_amount",
            "usable_amount",
        ):
            amount = getattr(self, amount_name)
            if not isinstance(amount, timedelta) or amount < timedelta(0):
                raise CapacityAnalysisError(
                    f"{amount_name} must be a non-negative timedelta"
                )
        if self.occupying_amount > self.availability_amount:
            raise CapacityAnalysisError(
                "occupying_amount must not exceed availability_amount"
            )
        if self.constrained_amount > self.availability_amount:
            raise CapacityAnalysisError(
                "constrained_amount must not exceed availability_amount"
            )
        if self.planned_amount > self.availability_amount:
            raise CapacityAnalysisError(
                "planned_amount must not exceed availability_amount"
            )
        if isinstance(self.sample_count, bool) or not isinstance(
            self.sample_count, int
        ):
            raise CapacityAnalysisError("sample_count must be an integer")
        if self.sample_count < 0:
            raise CapacityAnalysisError("sample_count must not be negative")
        ratio = self.buffer_ratio
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            raise CapacityAnalysisError("buffer_ratio must be a number")
        if not math.isfinite(ratio) or not 0 <= ratio < 1:
            raise CapacityAnalysisError(
                "buffer_ratio must be at least 0 and less than 1"
            )
        object.__setattr__(self, "buffer_ratio", float(ratio))
        if self.reserved_amount > self.effective_amount:
            raise CapacityAnalysisError(
                "reserved_amount must not exceed effective_amount"
            )
        if self.usable_amount > self.effective_amount:
            raise CapacityAnalysisError(
                "usable_amount must not exceed effective_amount"
            )
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise CapacityAnalysisError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise CapacityAnalysisError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise CapacityAnalysisError("updated_at must not precede created_at")


def _total(intervals: list[Interval]) -> timedelta:
    return sum((end - start for start, end in intervals), timedelta(0))


def analyze_time_environment(
    calendar: Calendar,
    windows: tuple[AvailabilityWindow, ...],
    events: tuple[CalendarEvent, ...],
    constraints: tuple[Constraint, ...],
    *,
    period_start: datetime,
    period_end: datetime,
    history: tuple[CapacitySample, ...] = (),
    buffer: Buffer | None = None,
    analysis_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> CapacityAnalysis:
    """Analyze ``calendar``'s time environment over a period.

    ``windows``, ``events``, and ``constraints`` are the calendar's
    availability, commitments, and hard blocks — all must belong to the
    calendar. ``history`` supplies the past planned/observed capacity
    samples that adjust the plan into effective capacity; ``buffer``
    (optional) reserves its fraction of the effective amount.
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    if not isinstance(windows, tuple):
        raise CapacityAnalysisError("windows must be a tuple of AvailabilityWindow")
    for window in windows:
        if not isinstance(window, AvailabilityWindow):
            raise CapacityAnalysisError(
                "windows must be AvailabilityWindow instances"
            )
        if window.calendar_id != calendar.calendar_id:
            raise CapacityAnalysisError("window does not belong to this calendar")
    if not isinstance(events, tuple):
        raise CapacityAnalysisError("events must be a tuple of CalendarEvent")
    for event in events:
        if not isinstance(event, CalendarEvent):
            raise CapacityAnalysisError("events must be CalendarEvent instances")
        if event.calendar_id != calendar.calendar_id:
            raise CapacityAnalysisError("event does not belong to this calendar")
    if not isinstance(constraints, tuple):
        raise CapacityAnalysisError("constraints must be a tuple of Constraint")
    for constraint in constraints:
        if not isinstance(constraint, Constraint):
            raise CapacityAnalysisError(
                "constraints must be Constraint instances"
            )
        if constraint.calendar_id != calendar.calendar_id:
            raise CapacityAnalysisError(
                "constraint does not belong to this calendar"
            )
    if not isinstance(history, tuple):
        raise CapacityAnalysisError("history must be a tuple of CapacitySample")
    for sample in history:
        if not isinstance(sample, CapacitySample):
            raise CapacityAnalysisError("history must be CapacitySample instances")
    if buffer is not None and not isinstance(buffer, Buffer):
        raise CapacityAnalysisError("buffer must be a Buffer or None")
    if buffer is not None and buffer.calendar_id != calendar.calendar_id:
        raise CapacityAnalysisError("buffer does not belong to this calendar")
    require_utc("period_start", period_start, error=CapacityAnalysisError)
    require_utc("period_end", period_end, error=CapacityAnalysisError)
    if period_end <= period_start:
        raise CapacityAnalysisError("period_end must be after period_start")

    # Availability: merged window intervals over the period.
    available: list[Interval] = []
    for window in windows:
        available.extend(
            available_intervals(
                window, range_start=period_start, range_end=period_end
            )
        )
    merged_availability = _merge(available)
    availability_amount = _total(merged_availability)

    # Commitments: merged event intervals over the period (the whole
    # commitment load, whether or not it lands on available time).
    committed: list[Interval] = []
    for event in events:
        clipped = _clip(event.start, event.end, period_start, period_end)
        if clipped is not None:
            committed.append(clipped)
    merged_commitments = _merge(committed)
    commitment_amount = _total(merged_commitments)

    # Constraints: hard blocks remove availability like commitments do.
    blocked: list[Interval] = []
    for constraint in constraints:
        blocked.extend(
            blocked_intervals(
                constraint, range_start=period_start, range_end=period_end
            )
        )
    merged_blocks = _merge(blocked)
    unconstrained = _subtract(merged_availability, merged_blocks)
    constrained_amount = availability_amount - _total(unconstrained)

    # Planned: what the environment still yields — the TASK-038
    # semantics (commitments only consume available time) applied to
    # the constraint-cleared availability.
    planned_intervals = _subtract(unconstrained, merged_commitments)
    planned_amount = _total(planned_intervals)
    occupying_amount = _total(unconstrained) - planned_amount

    # Effective: the plan adjusted by history (TASK-040 semantics).
    now = created_at if created_at is not None else datetime.now(UTC)
    planned_record = PlannedCapacity(
        capacity_id=uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        period_start=period_start,
        period_end=period_end,
        amount=planned_amount,
        created_at=now,
        updated_at=now,
    )
    effective = compute_effective_capacity(
        planned_record, history, created_at=now
    )

    # Usable: the buffer's reserve carved from the effective amount.
    if buffer is None:
        buffer_ratio = 0.0
        reserved = timedelta(0)
        usable = effective.amount
    else:
        buffered = apply_buffer(buffer, effective)
        buffer_ratio = buffer.ratio
        reserved = buffered.reserved_amount
        usable = buffered.usable_amount

    return CapacityAnalysis(
        analysis_id=analysis_id if analysis_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        period_start=period_start,
        period_end=period_end,
        availability_amount=availability_amount,
        commitment_amount=commitment_amount,
        constrained_amount=constrained_amount,
        occupying_amount=occupying_amount,
        planned_amount=planned_amount,
        effective_amount=effective.amount,
        sample_count=len(history),
        buffer_ratio=buffer_ratio,
        reserved_amount=reserved,
        usable_amount=usable,
        created_at=now,
        updated_at=now,
    )
