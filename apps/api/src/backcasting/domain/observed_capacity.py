"""Observed capacity domain model.

Planned Capacity is the forward-looking estimate; Observed Capacity is
the backward-looking measurement ("Measurement: observed data",
``docs/02-CONCEPTUAL-MODEL.md``) — how much workable time actually
materialized over a period that has happened, computed from the
calendar as it really was (the availability windows that applied and
the events that actually occupy it).

The two share their semantics (:func:`workable_time`): merged
availability minus occupying commitments. What differs is *when* the
record is taken and what it means — and therefore the invariants:

- a period can only be measured after it has ended
  (``measured_at ≥ period_end``); you cannot observe the future;
- a measurement is an immutable fact of history: there is no
  ``updated_at`` and no revision path — a corrected measurement is a
  new record. This is what makes the planned/observed comparison
  (capacity variance, docs/07) meaningful.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backcasting.domain.availability import AvailabilityWindow
from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.planned_capacity import (
    PlannedCapacityError,
    workable_time,
)
from backcasting.domain.timezone import UTC, require_utc


class ObservedCapacityError(ValueError):
    """Raised when an observed-capacity invariant is violated."""


@dataclass(frozen=True)
class ObservedCapacity:
    """The measured workable time on a calendar over a past period."""

    capacity_id: uuid.UUID
    calendar_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    amount: timedelta
    measured_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.capacity_id, uuid.UUID):
            raise ObservedCapacityError("capacity_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise ObservedCapacityError("calendar_id must be a UUID")
        require_utc("period_start", self.period_start, error=ObservedCapacityError)
        require_utc("period_end", self.period_end, error=ObservedCapacityError)
        if self.period_end <= self.period_start:
            raise ObservedCapacityError("period_end must be after period_start")
        if not isinstance(self.amount, timedelta) or self.amount < timedelta(0):
            raise ObservedCapacityError("amount must be a non-negative timedelta")
        require_utc("measured_at", self.measured_at, error=ObservedCapacityError)
        if self.measured_at < self.period_end:
            raise ObservedCapacityError(
                "a period can only be measured after it has ended"
            )


def measure_observed_capacity(
    calendar: Calendar,
    windows: tuple[AvailabilityWindow, ...],
    events: tuple[CalendarEvent, ...] = (),
    *,
    range_start: datetime,
    range_end: datetime,
    capacity_id: uuid.UUID | None = None,
    measured_at: datetime | None = None,
) -> ObservedCapacity:
    """Measure the observed capacity of ``calendar`` over a past period.

    ``windows`` are the availability windows that applied over the
    period and ``events`` the commitments that actually occupy it;
    both must belong to the calendar. The amount uses the shared
    capacity semantics (:func:`workable_time`); the measurement is
    stamped at ``measured_at`` (default: now), which must not precede
    the period's end.
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    if not isinstance(windows, tuple):
        raise ObservedCapacityError("windows must be a tuple of AvailabilityWindow")
    for window in windows:
        if not isinstance(window, AvailabilityWindow):
            raise ObservedCapacityError(
                "windows must be AvailabilityWindow instances"
            )
        if window.calendar_id != calendar.calendar_id:
            raise ObservedCapacityError("window does not belong to this calendar")
    if not isinstance(events, tuple):
        raise ObservedCapacityError("events must be a tuple of CalendarEvent")
    for event in events:
        if not isinstance(event, CalendarEvent):
            raise ObservedCapacityError("events must be CalendarEvent instances")
        if event.calendar_id != calendar.calendar_id:
            raise ObservedCapacityError("event does not belong to this calendar")

    try:
        amount = workable_time(
            windows, events, range_start=range_start, range_end=range_end
        )
    except PlannedCapacityError as exc:
        raise ObservedCapacityError(str(exc)) from exc

    now = measured_at if measured_at is not None else datetime.now(UTC)
    return ObservedCapacity(
        capacity_id=capacity_id if capacity_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        period_start=range_start,
        period_end=range_end,
        amount=amount,
        measured_at=now,
    )
