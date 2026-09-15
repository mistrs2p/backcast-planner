"""Calendar event domain model.

A Calendar Event is a time-blocked entry on a user's calendar
(``docs/05-CALENDAR-MODEL.md``). "Calendar Event is not necessarily a
Task" (``docs/03-DOMAIN-MODEL.md``): an event may be the schedule of a
planned task or an unrelated commitment imported from the user's real
life — the scheduling hierarchy's "existing commitments".

Rules:

- IDs are UUIDs; ``calendar_id`` references the calendar the event
  belongs to.
- ``title`` is non-empty, stripped, ≤ 200 characters; ``description``
  is optional free text ≤ 5000 characters.
- ``start``/``end`` are timezone-aware UTC instants with
  ``end > start``; persisted instants are UTC per AGENTS.md §7.
- Events are *not* forced onto the 15-minute planning granularity:
  that granularity governs where planned tasks may be placed
  (time slots), while existing commitments arrive at whatever times
  reality gives them.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
- An event carries no lifecycle of its own — removal from the calendar
  is a future concern (cancellation/exceptions), not entity state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backcasting.domain.calendar import Calendar

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000


class CalendarEventError(ValueError):
    """Raised when a CalendarEvent invariant is violated."""


@dataclass(frozen=True)
class CalendarEvent:
    """A time-blocked entry on a calendar."""

    event_id: uuid.UUID
    calendar_id: uuid.UUID
    title: str
    start: datetime
    end: datetime
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, uuid.UUID):
            raise CalendarEventError("event_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise CalendarEventError("calendar_id must be a UUID")
        title = self.title
        if not isinstance(title, str) or not title.strip():
            raise CalendarEventError("title must be a non-empty string")
        if len(title.strip()) > MAX_TITLE_LENGTH:
            raise CalendarEventError(
                f"title must be at most {MAX_TITLE_LENGTH} characters"
            )
        object.__setattr__(self, "title", title.strip())
        description = self.description
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise CalendarEventError("description must be a string")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise CalendarEventError(
                f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        object.__setattr__(self, "description", description)
        for stamp_name in ("start", "end", "created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise CalendarEventError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise CalendarEventError(f"{stamp_name} must be in UTC")
        if self.end <= self.start:
            raise CalendarEventError("end must be after start")
        if self.updated_at < self.created_at:
            raise CalendarEventError("updated_at must not precede created_at")


def create_event(
    calendar: Calendar,
    title: str,
    start: datetime,
    end: datetime,
    *,
    description: str = "",
    event_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> CalendarEvent:
    """Create an event on ``calendar``.

    The event is bound to the calendar it belongs to; ``start``/``end``
    must be timezone-aware UTC instants with ``end > start``.
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    now = created_at if created_at is not None else datetime.now(timezone.utc)
    return CalendarEvent(
        event_id=event_id if event_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        title=title,
        start=start,
        end=end,
        description=description,
        created_at=now,
        updated_at=now,
    )
