"""Tests for the Calendar domain model (TASK-029).

Pins the calendar root's invariants: user ownership, a valid home
timezone, UTC stamps, and the MVP planning-granularity constant from
docs/05.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.calendar import (
    PLANNING_GRANULARITY,
    Calendar,
    CalendarError,
    create_calendar,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
LONDON = ZoneInfo("Europe/London")
TEHRAN = ZoneInfo("Asia/Tehran")


class TestPlanningGranularity:
    def test_mvp_planning_granularity_is_15_minutes(self) -> None:
        assert PLANNING_GRANULARITY == timedelta(minutes=15)


class TestCalendar:
    def _valid_kwargs(self) -> dict:
        return {
            "calendar_id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "timezone": LONDON,
            "created_at": CREATED,
            "updated_at": CREATED,
        }

    def test_valid_calendar_is_accepted(self) -> None:
        calendar = Calendar(**self._valid_kwargs())
        assert calendar.timezone is LONDON
        assert calendar.created_at == CREATED

    @pytest.mark.parametrize("field_name", ["calendar_id", "user_id"])
    def test_ids_must_be_uuids(self, field_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[field_name] = "not-a-uuid"
        with pytest.raises(CalendarError):
            Calendar(**kwargs)

    def test_timezone_must_be_zoneinfo(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["timezone"] = "Europe/London"
        with pytest.raises(CalendarError):
            Calendar(**kwargs)

    @pytest.mark.parametrize("stamp_name", ["created_at", "updated_at"])
    def test_stamps_must_be_timezone_aware(self, stamp_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[stamp_name] = datetime(2026, 1, 1)
        with pytest.raises(CalendarError):
            Calendar(**kwargs)

    @pytest.mark.parametrize("stamp_name", ["created_at", "updated_at"])
    def test_stamps_must_be_utc(self, stamp_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[stamp_name] = CREATED.astimezone(TEHRAN)
        with pytest.raises(CalendarError):
            Calendar(**kwargs)

    def test_updated_at_must_not_precede_created_at(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["updated_at"] = CREATED - timedelta(seconds=1)
        with pytest.raises(CalendarError):
            Calendar(**kwargs)

    def test_calendar_is_immutable(self) -> None:
        calendar = Calendar(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            calendar.timezone = TEHRAN  # type: ignore[misc]


class TestCreateCalendar:
    def test_creates_calendar_for_user(self) -> None:
        user_id = uuid.uuid4()
        calendar = create_calendar(user_id, timezone=TEHRAN, created_at=CREATED)
        assert isinstance(calendar.calendar_id, uuid.UUID)
        assert calendar.user_id == user_id
        assert calendar.timezone is TEHRAN
        assert calendar.created_at == CREATED
        assert calendar.updated_at == CREATED

    def test_timezone_defaults_to_utc(self) -> None:
        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        assert calendar.timezone == ZoneInfo("UTC")

    def test_injectable_id_and_clock(self) -> None:
        calendar_id = uuid.uuid4()
        calendar = create_calendar(
            uuid.uuid4(),
            timezone=LONDON,
            calendar_id=calendar_id,
            created_at=CREATED,
        )
        assert calendar.calendar_id == calendar_id
        assert calendar.created_at == CREATED

    def test_non_uuid_user_id_is_rejected(self) -> None:
        with pytest.raises(CalendarError):
            create_calendar("not-a-uuid", created_at=CREATED)  # type: ignore[arg-type]
