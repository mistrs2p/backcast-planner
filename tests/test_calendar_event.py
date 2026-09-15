"""Tests for the Calendar event domain model (TASK-030).

Pins the time-block invariants: UTC instants with end after start,
bounded title/description, calendar ownership, and the deliberate
non-alignment with the 15-minute planning granularity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.calendar_event import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    CalendarEvent,
    CalendarEventError,
    create_event,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
START = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
END = datetime(2026, 1, 5, 10, 30, tzinfo=timezone.utc)
TEHRAN = ZoneInfo("Asia/Tehran")


@pytest.fixture
def calendar() -> Calendar:
    return create_calendar(uuid.uuid4(), created_at=CREATED)


class TestCalendarEvent:
    def _valid_kwargs(self) -> dict:
        return {
            "event_id": uuid.uuid4(),
            "calendar_id": uuid.uuid4(),
            "title": "Team meeting",
            "start": START,
            "end": END,
            "created_at": CREATED,
            "updated_at": CREATED,
        }

    def test_valid_event_is_accepted(self) -> None:
        event = CalendarEvent(**self._valid_kwargs())
        assert event.title == "Team meeting"
        assert event.start == START
        assert event.end == END
        assert event.description == ""

    def test_title_is_stripped(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["title"] = "  Team meeting  "
        assert CalendarEvent(**kwargs).title == "Team meeting"

    @pytest.mark.parametrize(
        "title", ["", "   ", "x" * (MAX_TITLE_LENGTH + 1)]
    )
    def test_invalid_titles_are_rejected(self, title: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs["title"] = title
        with pytest.raises(CalendarEventError):
            CalendarEvent(**kwargs)

    def test_title_at_limit_is_accepted(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["title"] = "x" * MAX_TITLE_LENGTH
        assert CalendarEvent(**kwargs).title == "x" * MAX_TITLE_LENGTH

    def test_description_is_optional_and_bounded(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["description"] = "Weekly sync."
        assert CalendarEvent(**kwargs).description == "Weekly sync."
        kwargs["description"] = "x" * (MAX_DESCRIPTION_LENGTH + 1)
        with pytest.raises(CalendarEventError):
            CalendarEvent(**kwargs)

    @pytest.mark.parametrize(
        "start,end",
        [
            (END, START),  # reversed
            (START, START),  # zero duration
            (START, START - timedelta(seconds=1)),  # negative duration
        ],
    )
    def test_end_must_be_after_start(
        self, start: datetime, end: datetime
    ) -> None:
        kwargs = self._valid_kwargs()
        kwargs["start"] = start
        kwargs["end"] = end
        with pytest.raises(CalendarEventError):
            CalendarEvent(**kwargs)

    @pytest.mark.parametrize("stamp_name", ["start", "end", "created_at", "updated_at"])
    def test_stamps_must_be_timezone_aware(self, stamp_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[stamp_name] = datetime(2026, 1, 5, 9)
        with pytest.raises(CalendarEventError):
            CalendarEvent(**kwargs)

    @pytest.mark.parametrize("stamp_name", ["start", "end", "created_at", "updated_at"])
    def test_stamps_must_be_utc(self, stamp_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[stamp_name] = START.astimezone(TEHRAN)
        with pytest.raises(CalendarEventError):
            CalendarEvent(**kwargs)

    def test_updated_at_must_not_precede_created_at(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["updated_at"] = CREATED - timedelta(seconds=1)
        with pytest.raises(CalendarEventError):
            CalendarEvent(**kwargs)

    @pytest.mark.parametrize("field_name", ["event_id", "calendar_id"])
    def test_ids_must_be_uuids(self, field_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[field_name] = "not-a-uuid"
        with pytest.raises(CalendarEventError):
            CalendarEvent(**kwargs)

    def test_event_is_immutable(self) -> None:
        event = CalendarEvent(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            event.title = "Other"  # type: ignore[misc]

    def test_events_are_not_forced_onto_planning_granularity(self) -> None:
        # Existing commitments arrive at whatever times reality gives
        # them; the 15-minute granularity governs task placement.
        kwargs = self._valid_kwargs()
        kwargs["start"] = datetime(2026, 1, 5, 9, 7, tzinfo=timezone.utc)
        kwargs["end"] = datetime(2026, 1, 5, 9, 23, tzinfo=timezone.utc)
        event = CalendarEvent(**kwargs)
        assert event.start.minute == 7
        assert event.end.minute == 23

    def test_event_has_no_task_dependency(self) -> None:
        # "Calendar Event is not necessarily a Task" (docs/03): the
        # event stands alone; any task link is the schedule's concern.
        assert not hasattr(CalendarEvent, "task_id")


class TestCreateEvent:
    def test_creates_event_bound_to_calendar(self, calendar: Calendar) -> None:
        event = create_event(
            calendar, "Team meeting", START, END, created_at=CREATED
        )
        assert isinstance(event.event_id, uuid.UUID)
        assert event.calendar_id == calendar.calendar_id
        assert event.created_at == CREATED
        assert event.updated_at == CREATED

    def test_accepts_description(self, calendar: Calendar) -> None:
        event = create_event(
            calendar,
            "Team meeting",
            START,
            END,
            description="Weekly sync.",
            created_at=CREATED,
        )
        assert event.description == "Weekly sync."

    def test_injectable_id_and_clock(self, calendar: Calendar) -> None:
        event_id = uuid.uuid4()
        event = create_event(
            calendar,
            "Team meeting",
            START,
            END,
            event_id=event_id,
            created_at=CREATED,
        )
        assert event.event_id == event_id
        assert event.created_at == CREATED

    def test_rejects_non_calendar(self) -> None:
        with pytest.raises(TypeError):
            create_event("not a calendar", "Title", START, END)  # type: ignore[arg-type]

    def test_validates_time_window(self, calendar: Calendar) -> None:
        with pytest.raises(CalendarEventError):
            create_event(calendar, "Broken", END, START, created_at=CREATED)
