"""Planned capacity domain model.

"Availability ≠ Capacity" (``docs/00-PROJECT-CONTEXT.md``): availability
is *when* the user can work; capacity is *how much* workable time the
time environment yields. Planned capacity is the forward-looking
answer — over a period, the availability windows' total time minus the
existing commitments that occupy it. (What actually happened is
Observed Capacity; combining both is Effective Capacity — later tasks
in this epic.)

Rules:

- IDs are UUIDs; ``calendar_id`` references the calendar the capacity
  belongs to.
- ``period_start``/``period_end`` are timezone-aware UTC instants with
  ``period_end > period_start`` — the period the amount covers (a week
  for weekly planning; any range is representable).
- ``amount`` is a non-negative timedelta.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.

:func:`derive_planned_capacity` computes the amount deterministically:

- every availability window contributes its UTC intervals over the
  period (TASK-034 semantics: local wall-clock times preserved across
  DST, clipped to the period);
- overlapping and touching intervals — across windows *and* across
  events — are merged first, so no time is ever counted twice;
- commitments only reduce capacity where they occupy available time
  (a meeting outside the windows consumes none of it);
- the amount is the availability total minus the occupied part.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backcasting.domain.availability import AvailabilityWindow, available_intervals
from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.timezone import UTC, require_utc


class PlannedCapacityError(ValueError):
    """Raised when a planned-capacity invariant is violated."""


@dataclass(frozen=True)
class PlannedCapacity:
    """The planned workable time on a calendar over a period."""

    capacity_id: uuid.UUID
    calendar_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    amount: timedelta
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.capacity_id, uuid.UUID):
            raise PlannedCapacityError("capacity_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise PlannedCapacityError("calendar_id must be a UUID")
        require_utc("period_start", self.period_start, error=PlannedCapacityError)
        require_utc("period_end", self.period_end, error=PlannedCapacityError)
        if self.period_end <= self.period_start:
            raise PlannedCapacityError("period_end must be after period_start")
        if not isinstance(self.amount, timedelta) or self.amount < timedelta(0):
            raise PlannedCapacityError("amount must be a non-negative timedelta")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise PlannedCapacityError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise PlannedCapacityError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise PlannedCapacityError("updated_at must not precede created_at")


Interval = tuple[datetime, datetime]


def _merge(intervals: list[Interval]) -> list[Interval]:
    """Merge overlapping and touching intervals (sorted sweep)."""
    merged: list[list[datetime]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _clip(start: datetime, end: datetime, lo: datetime, hi: datetime) -> Interval | None:
    """Clip ``[start, end)`` to ``[lo, hi)``; ``None`` when empty."""
    clipped_start, clipped_end = max(start, lo), min(end, hi)
    return (clipped_start, clipped_end) if clipped_start < clipped_end else None


def _subtract(base: list[Interval], cuts: list[Interval]) -> list[Interval]:
    """Remove ``cuts`` from ``base`` (both merged and sorted)."""
    remaining: list[Interval] = []
    for start, end in base:
        pieces: list[Interval] = [(start, end)]
        for cut_start, cut_end in cuts:
            if cut_end <= start or cut_start >= end:
                continue
            split: list[Interval] = []
            for piece_start, piece_end in pieces:
                if cut_start > piece_start:
                    split.append((piece_start, min(cut_start, piece_end)))
                if cut_end < piece_end:
                    split.append((max(cut_end, piece_start), piece_end))
            pieces = [
                (piece_start, piece_end)
                for piece_start, piece_end in split
                if piece_start < piece_end
            ]
        remaining.extend(pieces)
    return remaining


def derive_planned_capacity(
    calendar: Calendar,
    windows: tuple[AvailabilityWindow, ...],
    events: tuple[CalendarEvent, ...] = (),
    *,
    range_start: datetime,
    range_end: datetime,
    capacity_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> PlannedCapacity:
    """Derive the planned capacity of ``calendar`` over a period.

    ``windows`` are the calendar's availability windows and ``events``
    its existing commitments; both must belong to the calendar. The
    amount is the merged availability time over
    ``[range_start, range_end)`` minus the commitment time occupying
    it (commitments outside the windows consume none of it).
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    if not isinstance(windows, tuple):
        raise PlannedCapacityError("windows must be a tuple of AvailabilityWindow")
    for window in windows:
        if not isinstance(window, AvailabilityWindow):
            raise PlannedCapacityError("windows must be AvailabilityWindow instances")
        if window.calendar_id != calendar.calendar_id:
            raise PlannedCapacityError("window does not belong to this calendar")
    if not isinstance(events, tuple):
        raise PlannedCapacityError("events must be a tuple of CalendarEvent")
    for event in events:
        if not isinstance(event, CalendarEvent):
            raise PlannedCapacityError("events must be CalendarEvent instances")
        if event.calendar_id != calendar.calendar_id:
            raise PlannedCapacityError("event does not belong to this calendar")
    require_utc("range_start", range_start, error=PlannedCapacityError)
    require_utc("range_end", range_end, error=PlannedCapacityError)
    if range_end <= range_start:
        raise PlannedCapacityError("range_end must be after range_start")

    available: list[Interval] = []
    for window in windows:
        available.extend(
            available_intervals(
                window, range_start=range_start, range_end=range_end
            )
        )
    merged_availability = _merge(available)

    committed: list[Interval] = []
    for event in events:
        clipped = _clip(event.start, event.end, range_start, range_end)
        if clipped is not None:
            committed.append(clipped)
    merged_commitments = _merge(committed)

    amount = timedelta(0)
    for start, end in _subtract(merged_availability, merged_commitments):
        amount += end - start

    now = created_at if created_at is not None else datetime.now(UTC)
    return PlannedCapacity(
        capacity_id=capacity_id if capacity_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        period_start=range_start,
        period_end=range_end,
        amount=amount,
        created_at=now,
        updated_at=now,
    )
