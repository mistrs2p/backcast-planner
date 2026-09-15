"""In-memory repository implementations.

Until the production persistence epic delivers SQLAlchemy mappings,
these implementations back the application with process-local storage.
They honor the port contracts exactly (insert-or-replace by id,
``None`` for absence, deterministic ordering) so swapping in the real
implementations later changes wiring, not behavior.
"""

from __future__ import annotations

import threading
import uuid

from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.repositories import (
    CalendarEventRepository,
    CalendarRepository,
    RepositoryError,
)


class InMemoryCalendarRepository(CalendarRepository):
    """Calendar port backed by dicts, safe for concurrent requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Calendar] = {}
        self._by_user: dict[uuid.UUID, Calendar] = {}
        self._lock = threading.Lock()

    def save(self, calendar: Calendar) -> None:
        with self._lock:
            previous = self._by_id.get(calendar.calendar_id)
            if previous is not None and previous.user_id != calendar.user_id:
                raise RepositoryError("calendar id already belongs to another user")
            self._by_id[calendar.calendar_id] = calendar
            self._by_user[calendar.user_id] = calendar

    def get(self, calendar_id: uuid.UUID) -> Calendar | None:
        with self._lock:
            return self._by_id.get(calendar_id)

    def get_by_user(self, user_id: uuid.UUID) -> Calendar | None:
        with self._lock:
            return self._by_user.get(user_id)


class InMemoryCalendarEventRepository(CalendarEventRepository):
    """Calendar-event port backed by a dict, safe for concurrent requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, CalendarEvent] = {}
        self._lock = threading.Lock()

    def save(self, event: CalendarEvent) -> None:
        with self._lock:
            self._by_id[event.event_id] = event

    def list_for_calendar(self, calendar_id: uuid.UUID) -> tuple[CalendarEvent, ...]:
        with self._lock:
            events = [e for e in self._by_id.values() if e.calendar_id == calendar_id]
        return tuple(sorted(events, key=lambda e: (e.start, e.event_id)))
