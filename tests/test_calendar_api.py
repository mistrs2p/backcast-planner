"""Tests for the calendar API (TASK-037).

Covers the three new layers: the in-memory repositories
(infrastructure), the ``CalendarService`` use cases (application), and
the HTTP surface (presentation) — including the status mapping
(404/409/422) and UTC normalization per docs/10.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.application.calendars import (
    CalendarAlreadyExistsError,
    CalendarNotFoundError,
    CalendarService,
    InvalidTimezoneError,
)
from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.conflict import Conflict
from backcasting.domain.repositories import RepositoryError
from backcasting.infrastructure.memory import (
    InMemoryCalendarEventRepository,
    InMemoryCalendarRepository,
)

UTC = timezone.utc
TEHRAN = ZoneInfo("Asia/Tehran")


def _service() -> CalendarService:
    return CalendarService(
        InMemoryCalendarRepository(), InMemoryCalendarEventRepository()
    )


class TestInMemoryCalendarRepository:
    def test_save_and_get_round_trip(self) -> None:
        repo = InMemoryCalendarRepository()
        calendar = Calendar(calendar_id=uuid.uuid4(), user_id=uuid.uuid4())
        repo.save(calendar)
        assert repo.get(calendar.calendar_id) is calendar

    def test_get_by_user(self) -> None:
        repo = InMemoryCalendarRepository()
        user_id = uuid.uuid4()
        calendar = Calendar(calendar_id=uuid.uuid4(), user_id=user_id)
        repo.save(calendar)
        assert repo.get_by_user(user_id) is calendar
        assert repo.get_by_user(uuid.uuid4()) is None

    def test_absence_is_not_an_error(self) -> None:
        repo = InMemoryCalendarRepository()
        assert repo.get(uuid.uuid4()) is None

    def test_save_replaces_by_id(self) -> None:
        repo = InMemoryCalendarRepository()
        user_id = uuid.uuid4()
        calendar_id = uuid.uuid4()
        first = Calendar(calendar_id=calendar_id, user_id=user_id)
        repo.save(first)
        second = Calendar(calendar_id=calendar_id, user_id=user_id,
                          timezone=TEHRAN)
        repo.save(second)
        assert repo.get(calendar_id) is second
        assert repo.get_by_user(user_id) is second

    def test_id_collision_across_users_is_rejected(self) -> None:
        repo = InMemoryCalendarRepository()
        calendar_id = uuid.uuid4()
        repo.save(Calendar(calendar_id=calendar_id, user_id=uuid.uuid4()))
        with pytest.raises(RepositoryError):
            repo.save(Calendar(calendar_id=calendar_id, user_id=uuid.uuid4()))


class TestInMemoryCalendarEventRepository:
    def test_save_and_list_for_calendar(self) -> None:
        repo = InMemoryCalendarEventRepository()
        calendar_id = uuid.uuid4()
        late = CalendarEvent(
            event_id=uuid.uuid4(),
            calendar_id=calendar_id,
            title="Late",
            start=datetime(2026, 6, 2, 9, tzinfo=UTC),
            end=datetime(2026, 6, 2, 10, tzinfo=UTC),
        )
        early = CalendarEvent(
            event_id=uuid.uuid4(),
            calendar_id=calendar_id,
            title="Early",
            start=datetime(2026, 6, 1, 9, tzinfo=UTC),
            end=datetime(2026, 6, 1, 10, tzinfo=UTC),
        )
        repo.save(late)
        repo.save(early)
        assert repo.list_for_calendar(calendar_id) == (early, late)

    def test_other_calendars_are_excluded(self) -> None:
        repo = InMemoryCalendarEventRepository()
        event = CalendarEvent(
            event_id=uuid.uuid4(),
            calendar_id=uuid.uuid4(),
            title="Elsewhere",
            start=datetime(2026, 6, 1, 9, tzinfo=UTC),
            end=datetime(2026, 6, 1, 10, tzinfo=UTC),
        )
        repo.save(event)
        assert repo.list_for_calendar(uuid.uuid4()) == ()


class TestCalendarServiceCreate:
    def test_creates_calendar_defaulting_to_utc(self) -> None:
        service = _service()
        user_id = uuid.uuid4()
        calendar = service.create_calendar(user_id=user_id)
        assert isinstance(calendar, Calendar)
        assert calendar.user_id == user_id
        assert calendar.timezone == ZoneInfo("UTC")

    def test_accepts_iana_name(self) -> None:
        calendar = _service().create_calendar(
            user_id=uuid.uuid4(), timezone="Asia/Tehran"
        )
        assert calendar.timezone is TEHRAN

    def test_accepts_zoneinfo(self) -> None:
        calendar = _service().create_calendar(
            user_id=uuid.uuid4(), timezone=TEHRAN
        )
        assert calendar.timezone is TEHRAN

    def test_rejects_unknown_timezone(self) -> None:
        with pytest.raises(InvalidTimezoneError, match="unknown timezone"):
            _service().create_calendar(user_id=uuid.uuid4(), timezone="Mars/Olympus")

    def test_second_calendar_for_user_is_rejected(self) -> None:
        service = _service()
        user_id = uuid.uuid4()
        service.create_calendar(user_id=user_id)
        with pytest.raises(CalendarAlreadyExistsError, match="one per user"):
            service.create_calendar(user_id=user_id)


class TestCalendarServiceEvents:
    def test_get_unknown_calendar_raises(self) -> None:
        with pytest.raises(CalendarNotFoundError):
            _service().get_calendar(uuid.uuid4())

    def test_add_event_returns_and_persists(self) -> None:
        service = _service()
        calendar = service.create_calendar(user_id=uuid.uuid4())
        event = service.add_event(
            calendar.calendar_id,
            title="Standup",
            start=datetime(2026, 6, 1, 9, tzinfo=UTC),
            end=datetime(2026, 6, 1, 9, 30, tzinfo=UTC),
        )
        assert isinstance(event, CalendarEvent)
        assert service.list_events(calendar.calendar_id) == (event,)

    def test_add_event_normalizes_offset_to_utc(self) -> None:
        service = _service()
        calendar = service.create_calendar(user_id=uuid.uuid4())
        event = service.add_event(
            calendar.calendar_id,
            title="Tehran meeting",
            start=datetime(2026, 6, 1, 12, 0, tzinfo=TEHRAN),  # 08:30 UTC
            end=datetime(2026, 6, 1, 13, 0, tzinfo=TEHRAN),
        )
        assert event.start == datetime(2026, 6, 1, 8, 30, tzinfo=UTC)
        assert event.end == datetime(2026, 6, 1, 9, 30, tzinfo=UTC)

    def test_add_event_rejects_naive_datetime(self) -> None:
        service = _service()
        calendar = service.create_calendar(user_id=uuid.uuid4())
        with pytest.raises(ValueError, match="start must be timezone-aware"):
            service.add_event(
                calendar.calendar_id,
                title="Naive",
                start=datetime(2026, 6, 1, 9),
                end=datetime(2026, 6, 1, 10),
            )

    def test_add_event_rejects_end_before_start(self) -> None:
        service = _service()
        calendar = service.create_calendar(user_id=uuid.uuid4())
        with pytest.raises(ValueError, match="end must be after start"):
            service.add_event(
                calendar.calendar_id,
                title="Backwards",
                start=datetime(2026, 6, 1, 10, tzinfo=UTC),
                end=datetime(2026, 6, 1, 9, tzinfo=UTC),
            )

    def test_add_event_unknown_calendar_raises(self) -> None:
        with pytest.raises(CalendarNotFoundError):
            _service().add_event(
                uuid.uuid4(),
                title="Ghost",
                start=datetime(2026, 6, 1, 9, tzinfo=UTC),
                end=datetime(2026, 6, 1, 10, tzinfo=UTC),
            )

    def test_list_events_unknown_calendar_raises(self) -> None:
        with pytest.raises(CalendarNotFoundError):
            _service().list_events(uuid.uuid4())

    def test_list_events_is_sorted_by_start(self) -> None:
        service = _service()
        calendar = service.create_calendar(user_id=uuid.uuid4())
        late = service.add_event(
            calendar.calendar_id,
            title="Late",
            start=datetime(2026, 6, 2, 9, tzinfo=UTC),
            end=datetime(2026, 6, 2, 10, tzinfo=UTC),
        )
        early = service.add_event(
            calendar.calendar_id,
            title="Early",
            start=datetime(2026, 6, 1, 9, tzinfo=UTC),
            end=datetime(2026, 6, 1, 10, tzinfo=UTC),
        )
        assert service.list_events(calendar.calendar_id) == (early, late)

    def test_detect_conflicts_reports_overlaps(self) -> None:
        service = _service()
        calendar = service.create_calendar(user_id=uuid.uuid4())
        first = service.add_event(
            calendar.calendar_id,
            title="A",
            start=datetime(2026, 6, 1, 9, tzinfo=UTC),
            end=datetime(2026, 6, 1, 11, tzinfo=UTC),
        )
        second = service.add_event(
            calendar.calendar_id,
            title="B",
            start=datetime(2026, 6, 1, 10, tzinfo=UTC),
            end=datetime(2026, 6, 1, 12, tzinfo=UTC),
        )
        service.add_event(  # touching, not conflicting
            calendar.calendar_id,
            title="C",
            start=datetime(2026, 6, 1, 12, tzinfo=UTC),
            end=datetime(2026, 6, 1, 13, tzinfo=UTC),
        )
        (conflict,) = service.detect_conflicts(calendar.calendar_id)
        assert isinstance(conflict, Conflict)
        assert conflict.first is first
        assert conflict.second is second
        assert conflict.start == datetime(2026, 6, 1, 10, tzinfo=UTC)
        assert conflict.end == datetime(2026, 6, 1, 11, tzinfo=UTC)

    def test_detect_conflicts_unknown_calendar_raises(self) -> None:
        with pytest.raises(CalendarNotFoundError):
            _service().detect_conflicts(uuid.uuid4())


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backcasting.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _create_calendar(client, **overrides) -> dict:
    payload = {"user_id": str(uuid.uuid4())}
    payload.update(overrides)
    response = client.post("/calendars", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _parse(moment: str) -> datetime:
    return datetime.fromisoformat(moment.replace("Z", "+00:00"))


class TestCalendarHttpApi:
    def test_create_calendar(self, client) -> None:
        user_id = uuid.uuid4()
        response = client.post("/calendars", json={"user_id": str(user_id)})
        assert response.status_code == 201
        body = response.json()
        assert body["user_id"] == str(user_id)
        assert body["timezone"] == "UTC"
        assert uuid.UUID(body["calendar_id"])

    def test_create_calendar_with_timezone(self, client) -> None:
        body = _create_calendar(client, timezone="Asia/Tehran")
        assert body["timezone"] == "Asia/Tehran"

    def test_second_calendar_for_user_is_409(self, client) -> None:
        user_id = str(uuid.uuid4())
        assert client.post("/calendars", json={"user_id": user_id}).status_code == 201
        response = client.post("/calendars", json={"user_id": user_id})
        assert response.status_code == 409
        assert "one per user" in response.json()["detail"]

    def test_unknown_timezone_is_422(self, client) -> None:
        response = client.post(
            "/calendars", json={"user_id": str(uuid.uuid4()), "timezone": "No/Where"}
        )
        assert response.status_code == 422

    def test_get_calendar(self, client) -> None:
        created = _create_calendar(client)
        response = client.get(f"/calendars/{created['calendar_id']}")
        assert response.status_code == 200
        assert response.json() == created

    def test_get_unknown_calendar_is_404(self, client) -> None:
        response = client.get(f"/calendars/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_create_event(self, client) -> None:
        calendar = _create_calendar(client)
        response = client.post(
            f"/calendars/{calendar['calendar_id']}/events",
            json={
                "title": "Standup",
                "start": "2026-06-01T09:00:00+00:00",
                "end": "2026-06-01T09:30:00+00:00",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["title"] == "Standup"
        assert _parse(body["start"]) == datetime(2026, 6, 1, 9, tzinfo=UTC)

    def test_create_event_normalizes_offset_to_utc(self, client) -> None:
        calendar = _create_calendar(client)
        response = client.post(
            f"/calendars/{calendar['calendar_id']}/events",
            json={
                "title": "Tehran meeting",
                "start": "2026-06-01T12:00:00+03:30",
                "end": "2026-06-01T13:00:00+03:30",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert _parse(body["start"]) == datetime(2026, 6, 1, 8, 30, tzinfo=UTC)
        assert _parse(body["end"]) == datetime(2026, 6, 1, 9, 30, tzinfo=UTC)

    def test_naive_event_datetime_is_422(self, client) -> None:
        calendar = _create_calendar(client)
        response = client.post(
            f"/calendars/{calendar['calendar_id']}/events",
            json={
                "title": "Naive",
                "start": "2026-06-01T09:00:00",
                "end": "2026-06-01T10:00:00",
            },
        )
        assert response.status_code == 422

    def test_end_before_start_is_422(self, client) -> None:
        calendar = _create_calendar(client)
        response = client.post(
            f"/calendars/{calendar['calendar_id']}/events",
            json={
                "title": "Backwards",
                "start": "2026-06-01T10:00:00+00:00",
                "end": "2026-06-01T09:00:00+00:00",
            },
        )
        assert response.status_code == 422
        assert "end must be after start" in response.json()["detail"]

    def test_event_on_unknown_calendar_is_404(self, client) -> None:
        response = client.post(
            f"/calendars/{uuid.uuid4()}/events",
            json={
                "title": "Ghost",
                "start": "2026-06-01T09:00:00+00:00",
                "end": "2026-06-01T10:00:00+00:00",
            },
        )
        assert response.status_code == 404

    def test_list_events_sorted_by_start(self, client) -> None:
        calendar = _create_calendar(client)
        base = f"/calendars/{calendar['calendar_id']}/events"
        for day, hour in ((2, 9), (1, 9), (1, 15)):
            assert client.post(
                base,
                json={
                    "title": f"E{day}-{hour}",
                    "start": f"2026-06-{day:02d}T{hour:02d}:00:00+00:00",
                    "end": f"2026-06-{day:02d}T{hour + 1:02d}:00:00+00:00",
                },
            ).status_code == 201
        body = client.get(base).json()
        assert [e["title"] for e in body] == ["E1-9", "E1-15", "E2-9"]

    def test_list_events_unknown_calendar_is_404(self, client) -> None:
        assert client.get(f"/calendars/{uuid.uuid4()}/events").status_code == 404

    def test_conflicts_over_http(self, client) -> None:
        calendar = _create_calendar(client)
        base = f"/calendars/{calendar['calendar_id']}/events"
        for title, start, end in (
            ("A", "2026-06-01T09:00:00+00:00", "2026-06-01T11:00:00+00:00"),
            ("B", "2026-06-01T10:00:00+00:00", "2026-06-01T12:00:00+00:00"),
            ("C", "2026-06-01T12:00:00+00:00", "2026-06-01T13:00:00+00:00"),
        ):
            assert client.post(
                base, json={"title": title, "start": start, "end": end}
            ).status_code == 201
        response = client.get(f"/calendars/{calendar['calendar_id']}/conflicts")
        assert response.status_code == 200
        (conflict,) = response.json()
        assert conflict["first"]["title"] == "A"
        assert conflict["second"]["title"] == "B"
        assert _parse(conflict["start"]) == datetime(2026, 6, 1, 10, tzinfo=UTC)
        assert _parse(conflict["end"]) == datetime(2026, 6, 1, 11, tzinfo=UTC)

    def test_conflicts_unknown_calendar_is_404(self, client) -> None:
        response = client.get(f"/calendars/{uuid.uuid4()}/conflicts")
        assert response.status_code == 404

    def test_calendars_are_isolated_per_app(self) -> None:
        from fastapi.testclient import TestClient

        from backcasting.app import create_app

        with TestClient(create_app()) as first_client:
            calendar = _create_calendar(first_client)
        with TestClient(create_app()) as second_client:
            response = second_client.get(f"/calendars/{calendar['calendar_id']}")
        assert response.status_code == 404


class TestCalendarForUser:
    """The by-user lookup the calendar UI resolves from (TASK-113)."""

    def test_service_returns_none_before_creation(self) -> None:
        assert _service().get_for_user(uuid.uuid4()) is None

    def test_service_returns_the_users_calendar(self) -> None:
        service = _service()
        user_id = uuid.uuid4()
        calendar = service.create_calendar(user_id=user_id)
        assert service.get_for_user(user_id) is calendar
        assert service.get_for_user(uuid.uuid4()) is None

    def test_http_404_before_creation(self, client) -> None:
        response = client.get(f"/users/{uuid.uuid4()}/calendar")
        assert response.status_code == 404
        assert "no calendar for user" in response.json()["detail"]

    def test_http_returns_the_calendar_after_creation(self, client) -> None:
        user_id = uuid.uuid4()
        created = client.post(
            "/calendars", json={"user_id": str(user_id), "timezone": "Asia/Tehran"}
        ).json()
        response = client.get(f"/users/{user_id}/calendar")
        assert response.status_code == 200
        body = response.json()
        assert body["calendar_id"] == created["calendar_id"]
        assert body["user_id"] == str(user_id)
        assert body["timezone"] == "Asia/Tehran"

    def test_http_contract_path(self, client) -> None:
        schema = client.app.openapi()
        assert "/users/{user_id}/calendar" in schema["paths"]


class TestContract:
    def test_openapi_documents_calendar_routes(self, client) -> None:
        schema = client.app.openapi()
        paths = schema["paths"]
        for path in (
            "/calendars",
            "/calendars/{calendar_id}",
            "/calendars/{calendar_id}/events",
            "/calendars/{calendar_id}/conflicts",
        ):
            assert path in paths, f"missing contract path {path}"

    def test_committed_contract_has_no_drift(self) -> None:
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(repo_root / "scripts" / "generate_contracts.py"),
             "--check"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.fail(
                "committed OpenAPI contract drifted from the app — regenerate "
                f"with scripts/generate_contracts.py:\n{result.stdout}{result.stderr}"
            )
