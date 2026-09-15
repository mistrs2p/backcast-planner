"""Calendar conflict detection.

Two commitments compete for the same time when their intervals overlap
on one calendar. Detecting that overlap is deterministic — the Domain's
job per ADR-002 — while *resolving* a conflict (rescheduling first,
escalating to replanning only when Plan-level feasibility is affected,
``docs/06-PLANNING-SCHEDULING.md``) belongs to the planning epic.

Semantics:

- Intervals are half-open ``[start, end)``: two events *touch* when one
  ends exactly as the other begins — back-to-back commitments are not a
  conflict. Overlap requires a strictly positive shared interval.
- All events must belong to the same calendar: a conflict is a clash
  within one user's commitments.
- A :class:`Conflict` carries both events and the shared interval
  (``start``/``end`` UTC instants; its length is ``end - start``).
- Results are deterministic regardless of input order: events are swept
  in ``(start, end, event_id)`` order and each clashing pair is
  reported exactly once, in sweep order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent


class ConflictError(ValueError):
    """Raised when a conflict-detection invariant is violated."""


@dataclass(frozen=True)
class Conflict:
    """Two calendar events competing for the same time."""

    first: CalendarEvent
    second: CalendarEvent
    start: datetime
    end: datetime


def detect_conflicts(
    calendar: Calendar,
    events: tuple[CalendarEvent, ...],
) -> tuple[Conflict, ...]:
    """Detect overlapping event pairs among ``events`` on ``calendar``.

    Every event must belong to ``calendar``. Each clashing pair appears
    once, with ``first`` the event that starts earlier (ties broken by
    end, then event id); ``start``/``end`` delimit the shared interval.
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    if not isinstance(events, tuple):
        raise ConflictError("events must be a tuple of CalendarEvent")
    for event in events:
        if not isinstance(event, CalendarEvent):
            raise ConflictError("events must be CalendarEvent instances")
        if event.calendar_id != calendar.calendar_id:
            raise ConflictError("event does not belong to this calendar")

    ordered = sorted(events, key=lambda e: (e.start, e.end, e.event_id))
    conflicts: list[Conflict] = []
    for i, first in enumerate(ordered):
        for second in ordered[i + 1 :]:
            if second.start >= first.end:
                break  # later events start even later — no overlap left
            conflicts.append(
                Conflict(
                    first=first,
                    second=second,
                    start=second.start,
                    end=min(first.end, second.end),
                )
            )
    return tuple(conflicts)
