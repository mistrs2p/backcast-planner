"""Calendar use cases.

The application layer composes domain operations into the use cases the
API exposes ("API exposes use cases", docs/10-TECHNICAL-ARCHITECTURE.md):
creating a user's calendar, placing events on it, and detecting the
conflicts among those events. All domain rules stay in
``backcasting.domain`` — this layer only orchestrates the ports.

Persistence is whatever the injected repositories do; until the
production persistence epic the application ships with in-memory
implementations (``backcasting.infrastructure.memory``).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.calendar_event import CalendarEvent, create_event
from backcasting.domain.conflict import Conflict, detect_conflicts
from backcasting.domain.repositories import (
    CalendarEventRepository,
    CalendarRepository,
)
from backcasting.domain.timezone import to_utc


class CalendarApplicationError(Exception):
    """Base for calendar use-case failures."""


class CalendarNotFoundError(CalendarApplicationError):
    """No calendar exists under the referenced id."""


class CalendarAlreadyExistsError(CalendarApplicationError):
    """The user already owns a calendar (one per user in the MVP)."""


class InvalidTimezoneError(CalendarApplicationError):
    """The requested timezone is not a valid IANA zone name."""


class CalendarService:
    """The calendar use cases, wired to persistence ports."""

    def __init__(
        self,
        calendars: CalendarRepository,
        events: CalendarEventRepository,
    ) -> None:
        self._calendars = calendars
        self._events = events

    def create_calendar(
        self, *, user_id, timezone: str | ZoneInfo | None = None
    ) -> Calendar:
        """Create the user's calendar (MVP: one per user).

        ``timezone`` is the calendar's home zone — an IANA name or
        :class:`~zoneinfo.ZoneInfo`, defaulting to UTC.
        """
        if isinstance(timezone, str):
            try:
                timezone = ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise InvalidTimezoneError(
                    f"unknown timezone: {timezone}"
                ) from exc
        if self._calendars.get_by_user(user_id) is not None:
            raise CalendarAlreadyExistsError(
                "user already owns a calendar (one per user in the MVP)"
            )
        calendar = create_calendar(user_id, timezone=timezone)
        self._calendars.save(calendar)
        return calendar

    def get_calendar(self, calendar_id) -> Calendar:
        """Return the calendar, or raise :class:`CalendarNotFoundError`."""
        calendar = self._calendars.get(calendar_id)
        if calendar is None:
            raise CalendarNotFoundError(f"no calendar {calendar_id}")
        return calendar

    def add_event(
        self,
        calendar_id,
        *,
        title: str,
        start: datetime,
        end: datetime,
        description: str = "",
    ) -> CalendarEvent:
        """Place an event on the calendar.

        ``start``/``end`` may carry any UTC offset; they are normalized
        to UTC per the persistence rule (docs/10). Naive datetimes are
        rejected — a missing zone is never guessed.
        """
        calendar = self.get_calendar(calendar_id)
        event = create_event(
            calendar,
            title,
            to_utc(start, name="start"),
            to_utc(end, name="end"),
            description=description,
        )
        self._events.save(event)
        return event

    def list_events(self, calendar_id) -> tuple[CalendarEvent, ...]:
        """Return the calendar's events, earliest start first."""
        self.get_calendar(calendar_id)  # 404 before an empty listing
        return tuple(self._events.list_for_calendar(calendar_id))

    def detect_conflicts(self, calendar_id) -> tuple[Conflict, ...]:
        """Report the overlapping event pairs on the calendar."""
        calendar = self.get_calendar(calendar_id)
        events = self._events.list_for_calendar(calendar_id)
        return detect_conflicts(calendar, tuple(events))


__all__ = [
    "CalendarAlreadyExistsError",
    "CalendarApplicationError",
    "CalendarNotFoundError",
    "CalendarService",
    "InvalidTimezoneError",
]
