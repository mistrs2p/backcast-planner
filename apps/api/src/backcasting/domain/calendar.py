"""Calendar domain model.

A Calendar is a User's temporal environment (``docs/05-CALENDAR-MODEL.md``
"Calendar belongs to User"): the aggregate its events, recurrence
rules, exceptions, availability windows, and floating rest live under.
Those pieces arrive in the following tasks; this module defines the
root.

Rules:

- IDs are UUIDs; ``user_id`` references the owning user.
- ``timezone`` is a valid :class:`zoneinfo.ZoneInfo` — the calendar's
  home zone, anchoring all timezone-aware operations (docs/05:
  "Timezone-aware operations are mandatory"). It defaults to the owning
  user's timezone but may be overridden explicitly.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
- Planning granularity is fixed at 15 minutes for the MVP (docs/05); it
  is an MVP-wide constant, not per-calendar state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backcasting.domain.timezone import UTC

#: The MVP planning granularity (docs/05-CALENDAR-MODEL.md).
PLANNING_GRANULARITY = timedelta(minutes=15)


class CalendarError(ValueError):
    """Raised when a Calendar invariant is violated."""


@dataclass(frozen=True)
class Calendar:
    """A user's calendar: the root of their temporal environment."""

    calendar_id: uuid.UUID
    user_id: uuid.UUID
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.calendar_id, uuid.UUID):
            raise CalendarError("calendar_id must be a UUID")
        if not isinstance(self.user_id, uuid.UUID):
            raise CalendarError("user_id must be a UUID")
        if not isinstance(self.timezone, ZoneInfo):
            raise CalendarError("timezone must be a ZoneInfo")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise CalendarError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise CalendarError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise CalendarError("updated_at must not precede created_at")


def create_calendar(
    user_id: uuid.UUID,
    *,
    timezone: ZoneInfo | None = None,
    calendar_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Calendar:
    """Create a calendar for a user.

    ``timezone`` anchors the calendar's timezone-aware operations; when
    omitted the caller supplies the owning user's zone explicitly (the
    user's own default is applied by the caller, keeping this factory
    free of a User dependency).
    """
    if not isinstance(user_id, uuid.UUID):
        raise CalendarError("user_id must be a UUID")
    now = created_at if created_at is not None else datetime.now(UTC)
    return Calendar(
        calendar_id=calendar_id if calendar_id is not None else uuid.uuid4(),
        user_id=user_id,
        timezone=timezone if timezone is not None else ZoneInfo("UTC"),
        created_at=now,
        updated_at=now,
    )
