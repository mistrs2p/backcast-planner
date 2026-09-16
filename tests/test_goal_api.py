"""Tests for the goal API (TASK-107).

Covers the new slices end to end: the in-memory repository
(infrastructure), the ``GoalService`` use cases (application), and the
HTTP surface (presentation) — including the status mapping (404/422)
and the user-scoped, oldest-first listing per docs/03 and docs/10.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.goals import GoalNotFoundError, GoalService
from backcasting.domain.goal import Goal, GoalError, create_goal
from backcasting.infrastructure.memory import InMemoryGoalRepository

UTC = timezone.utc


def _service() -> GoalService:
    return GoalService(InMemoryGoalRepository())


class TestInMemoryGoalRepository:
    def test_save_and_get_round_trip(self) -> None:
        repo = InMemoryGoalRepository()
        goal = create_goal(uuid.uuid4(), "Learn Rust")
        repo.save(goal)
        assert repo.get(goal.goal_id) is goal

    def test_absence_is_not_an_error(self) -> None:
        repo = InMemoryGoalRepository()
        assert repo.get(uuid.uuid4()) is None

    def test_save_replaces_by_id(self) -> None:
        repo = InMemoryGoalRepository()
        goal = create_goal(uuid.uuid4(), "First")
        repo.save(goal)
        revised = Goal(
            goal_id=goal.goal_id,
            user_id=goal.user_id,
            title="Revised",
            created_at=goal.created_at,
            updated_at=goal.updated_at + timedelta(minutes=1),
        )
        repo.save(revised)
        assert repo.get(goal.goal_id) is revised

    def test_list_for_user_filters_and_orders_oldest_first(self) -> None:
        repo = InMemoryGoalRepository()
        user_id = uuid.uuid4()
        later = create_goal(
            user_id, "Later", created_at=datetime(2026, 6, 2, tzinfo=UTC)
        )
        earlier = create_goal(
            user_id, "Earlier", created_at=datetime(2026, 6, 1, tzinfo=UTC)
        )
        other_user_goal = create_goal(uuid.uuid4(), "Elsewhere")
        repo.save(later)
        repo.save(earlier)
        repo.save(other_user_goal)
        assert repo.list_for_user(user_id) == (earlier, later)

    def test_list_for_user_with_no_goals_is_empty(self) -> None:
        assert InMemoryGoalRepository().list_for_user(uuid.uuid4()) == ()


class TestGoalService:
    def test_create_goal_returns_and_persists(self) -> None:
        service = _service()
        user_id = uuid.uuid4()
        goal = service.create_goal(
            user_id=user_id, title="Run a marathon", description="By December"
        )
        assert isinstance(goal, Goal)
        assert goal.user_id == user_id
        assert goal.title == "Run a marathon"
        assert goal.description == "By December"
        assert service.get_goal(goal.goal_id) == goal

    def test_created_goal_starts_in_draft(self) -> None:
        goal = _service().create_goal(user_id=uuid.uuid4(), title="Draft me")
        assert goal.status.value == "draft"

    def test_title_is_stripped(self) -> None:
        goal = _service().create_goal(user_id=uuid.uuid4(), title="  Padded  ")
        assert goal.title == "Padded"

    def test_blank_title_raises_goal_error(self) -> None:
        with pytest.raises(GoalError, match="non-empty"):
            _service().create_goal(user_id=uuid.uuid4(), title="   ")

    def test_oversized_title_raises_goal_error(self) -> None:
        with pytest.raises(GoalError, match="at most"):
            _service().create_goal(user_id=uuid.uuid4(), title="x" * 201)

    def test_get_unknown_goal_raises(self) -> None:
        with pytest.raises(GoalNotFoundError):
            _service().get_goal(uuid.uuid4())

    def test_list_for_user_returns_all_goals_of_user(self) -> None:
        # Ordering (oldest first) is enforced by the repository's
        # (created_at, goal_id) sort and covered there with injected
        # timestamps; here successive creates can share a clock tick.
        service = _service()
        user_id = uuid.uuid4()
        later = service.create_goal(user_id=user_id, title="Later")
        earlier = service.create_goal(user_id=user_id, title="Earlier")
        assert set(service.list_for_user(user_id)) == {earlier, later}

    def test_list_is_scoped_to_the_user(self) -> None:
        service = _service()
        goal = service.create_goal(user_id=uuid.uuid4(), title="Mine")
        assert service.list_for_user(uuid.uuid4()) == ()
        assert service.list_for_user(goal.user_id) == (goal,)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backcasting.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _create_goal(client, **overrides) -> dict:
    payload = {"user_id": str(uuid.uuid4()), "title": "Ship the MVP"}
    payload.update(overrides)
    response = client.post("/goals", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


class TestGoalHttpApi:
    def test_create_goal(self, client) -> None:
        user_id = uuid.uuid4()
        response = client.post(
            "/goals",
            json={
                "user_id": str(user_id),
                "title": "Learn to sail",
                "description": "Coastal skipper by summer",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["user_id"] == str(user_id)
        assert body["title"] == "Learn to sail"
        assert body["description"] == "Coastal skipper by summer"
        assert body["status"] == "draft"
        assert uuid.UUID(body["goal_id"])
        # timestamps are UTC ISO-8601
        for moment in (body["created_at"], body["updated_at"]):
            parsed = datetime.fromisoformat(moment)
            assert parsed.tzinfo is not None
            assert parsed.utcoffset() == timedelta(0)

    def test_create_goal_without_description(self, client) -> None:
        body = _create_goal(client)
        assert body["description"] == ""

    def test_blank_title_is_422(self, client) -> None:
        response = client.post(
            "/goals",
            json={"user_id": str(uuid.uuid4()), "title": "   "},
        )
        assert response.status_code == 422
        assert "non-empty" in response.json()["detail"]

    def test_oversized_title_is_422(self, client) -> None:
        response = client.post(
            "/goals",
            json={"user_id": str(uuid.uuid4()), "title": "x" * 201},
        )
        assert response.status_code == 422

    def test_get_goal(self, client) -> None:
        created = _create_goal(client)
        response = client.get(f"/goals/{created['goal_id']}")
        assert response.status_code == 200
        assert response.json() == created

    def test_get_unknown_goal_is_404(self, client) -> None:
        assert client.get(f"/goals/{uuid.uuid4()}").status_code == 404

    def test_get_malformed_goal_id_is_422(self, client) -> None:
        assert client.get("/goals/not-a-uuid").status_code == 422

    def test_list_goals_requires_user_id(self, client) -> None:
        assert client.get("/goals").status_code == 422

    def test_list_goals_scopes_to_user(self, client) -> None:
        user_id = str(uuid.uuid4())
        for title in ("Second", "First"):
            response = client.post(
                "/goals", json={"user_id": user_id, "title": title}
            )
            assert response.status_code == 201
        other = _create_goal(client, title="Someone else's")
        body = client.get("/goals", params={"user_id": user_id}).json()
        assert {goal["title"] for goal in body} == {"Second", "First"}
        assert all(goal["user_id"] == user_id for goal in body)
        assert other["title"] not in {goal["title"] for goal in body}

    def test_list_goals_unknown_user_is_empty(self, client) -> None:
        body = client.get("/goals", params={"user_id": str(uuid.uuid4())}).json()
        assert body == []

    def test_goals_are_isolated_per_app(self) -> None:
        from fastapi.testclient import TestClient

        from backcasting.app import create_app

        with TestClient(create_app()) as first_client:
            goal = _create_goal(first_client)
        with TestClient(create_app()) as second_client:
            response = second_client.get(f"/goals/{goal['goal_id']}")
        assert response.status_code == 404


class TestContract:
    def test_openapi_documents_goal_routes(self, client) -> None:
        schema = client.app.openapi()
        paths = schema["paths"]
        for path in ("/goals", "/goals/{goal_id}"):
            assert path in paths, f"missing contract path {path}"
        operations = paths["/goals"]
        assert "post" in operations
        assert "get" in operations
