"""Tests for the backcast API (TASK-109).

Covers pipeline steps 1–4 as one composed capability: the
in-memory repositories (including the one-per-goal invariants),
the ``BackcastService`` use cases, and the HTTP surface with its
status mapping (404/409/422) — the chain the UI visualizes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.backcast import (
    BackcastAlreadyExistsError,
    BackcastService,
)
from backcasting.application.goals import GoalNotFoundError
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import calculate_gap
from backcasting.domain.repositories import RepositoryError
from backcasting.infrastructure.memory import (
    InMemoryCurrentStateRepository,
    InMemoryFutureStateRepository,
    InMemoryGapRepository,
    InMemoryGoalRepository,
)

UTC = timezone.utc
TARGET = datetime(2026, 12, 31, tzinfo=UTC)


def _service() -> BackcastService:
    goals = InMemoryGoalRepository()
    return BackcastService(
        goals,
        InMemoryCurrentStateRepository(),
        InMemoryFutureStateRepository(),
        InMemoryGapRepository(),
    )


def _goal(service: BackcastService):
    from backcasting.domain.goal import create_goal

    goal = create_goal(uuid.uuid4(), "Run a marathon")
    service._goals.save(goal)
    return goal


class TestInMemoryStateRepositories:
    def test_current_state_save_list_latest(self) -> None:
        repo = InMemoryCurrentStateRepository()
        goal_id = uuid.uuid4()
        earlier = capture_current_state(
            goal_id, "Earlier", captured_at=datetime(2026, 6, 1, tzinfo=UTC)
        )
        later = capture_current_state(
            goal_id, "Later", captured_at=datetime(2026, 6, 2, tzinfo=UTC)
        )
        other = capture_current_state(uuid.uuid4(), "Elsewhere")
        repo.save(later)
        repo.save(earlier)
        repo.save(other)
        assert repo.list_for_goal(goal_id) == (earlier, later)
        assert repo.latest_for_goal(goal_id) is later
        assert repo.get(earlier.state_id) is earlier
        assert repo.latest_for_goal(uuid.uuid4()) is None

    def test_future_state_one_per_goal(self) -> None:
        repo = InMemoryFutureStateRepository()
        goal_id = uuid.uuid4()
        first = define_future_state(goal_id, "First", TARGET)
        repo.save(first)
        assert repo.get_for_goal(goal_id) is first
        with pytest.raises(RepositoryError, match="one per goal"):
            repo.save(define_future_state(goal_id, "Second", TARGET))

    def test_future_state_save_replaces_by_id(self) -> None:
        repo = InMemoryFutureStateRepository()
        goal_id = uuid.uuid4()
        first = define_future_state(
            goal_id, "First", TARGET, created_at=datetime(2026, 6, 1, tzinfo=UTC)
        )
        repo.save(first)
        revised = define_future_state(
            goal_id,
            "Revised",
            TARGET + timedelta(days=1),
            state_id=first.state_id,
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        repo.save(revised)
        assert repo.get_for_goal(goal_id) is revised

    def test_gap_one_per_goal(self) -> None:
        repo = InMemoryGapRepository()
        goal_id = uuid.uuid4()
        first = calculate_gap(
            _make_goal(goal_id),
            capture_current_state(goal_id, "Now"),
            define_future_state(goal_id, "Then", TARGET),
        )
        repo.save(first)
        assert repo.get_for_goal(goal_id) is first
        second = calculate_gap(
            _make_goal(goal_id),
            capture_current_state(goal_id, "Now again"),
            define_future_state(goal_id, "Then", TARGET),
        )
        with pytest.raises(RepositoryError, match="one per goal"):
            repo.save(second)


def _make_goal(goal_id):
    from backcasting.domain.goal import Goal, GoalStatus

    return Goal(
        goal_id=goal_id,
        user_id=uuid.uuid4(),
        title="Run a marathon",
        status=GoalStatus.DRAFT,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        updated_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


class TestBackcastService:
    def test_define_backcast_returns_and_persists_bundle(self) -> None:
        service = _service()
        goal = _goal(service)
        bundle = service.define_backcast(
            goal_id=goal.goal_id,
            current_narrative="Couch potato, 0km weekly",
            future_description="Finish a full marathon",
            target_date=TARGET,
            gap_narrative="42.2km of distance to cross",
        )
        assert bundle.current.narrative == "Couch potato, 0km weekly"
        assert bundle.future.description == "Finish a full marathon"
        assert bundle.future.target_date == TARGET
        assert bundle.gap.narrative == "42.2km of distance to cross"
        assert bundle.gap.current_state_id == bundle.current.state_id
        assert bundle.gap.future_state_id == bundle.future.state_id
        # all three artifacts are retrievable
        assert service.get_backcast(goal.goal_id) == bundle

    def test_define_backcast_unknown_goal_raises(self) -> None:
        with pytest.raises(GoalNotFoundError):
            _service().define_backcast(
                goal_id=uuid.uuid4(),
                current_narrative="Now",
                future_description="Then",
                target_date=TARGET,
            )

    def test_second_backcast_for_goal_is_rejected(self) -> None:
        service = _service()
        goal = _goal(service)
        service.define_backcast(
            goal_id=goal.goal_id,
            current_narrative="Now",
            future_description="Then",
            target_date=TARGET,
        )
        with pytest.raises(BackcastAlreadyExistsError, match="one per goal"):
            service.define_backcast(
                goal_id=goal.goal_id,
                current_narrative="Now",
                future_description="Then",
                target_date=TARGET,
            )

    def test_target_date_in_past_is_rejected(self) -> None:
        service = _service()
        goal = _goal(service)
        with pytest.raises(ValueError, match="after"):
            service.define_backcast(
                goal_id=goal.goal_id,
                current_narrative="Now",
                future_description="Then",
                target_date=datetime(2020, 1, 1, tzinfo=UTC),
            )

    def test_blank_current_narrative_is_rejected(self) -> None:
        service = _service()
        goal = _goal(service)
        with pytest.raises(ValueError, match="non-empty"):
            service.define_backcast(
                goal_id=goal.goal_id,
                current_narrative="   ",
                future_description="Then",
                target_date=TARGET,
            )

    def test_get_backcast_without_definition_is_none(self) -> None:
        service = _service()
        goal = _goal(service)
        assert service.get_backcast(goal.goal_id) is None


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backcasting.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _create_goal(client) -> dict:
    response = client.post(
        "/goals",
        json={"user_id": str(uuid.uuid4()), "title": "Run a marathon"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _define_backcast(client, goal_id, **overrides) -> dict:
    payload = {
        "current_narrative": "Couch potato, 0km weekly",
        "future_description": "Finish a full marathon",
        "target_date": "2026-12-31T00:00:00+00:00",
        "gap_narrative": "42.2km of distance to cross",
    }
    payload.update(overrides)
    response = client.post(f"/goals/{goal_id}/backcast", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


class TestBackcastHttpApi:
    def test_define_backcast(self, client) -> None:
        goal = _create_goal(client)
        body = _define_backcast(client, goal["goal_id"])
        assert body["current"]["narrative"] == "Couch potato, 0km weekly"
        assert body["future"]["description"] == "Finish a full marathon"
        assert body["future"]["target_date"].endswith("+00:00")
        assert body["gap"]["narrative"] == "42.2km of distance to cross"
        assert body["gap"]["dimensions"] == []
        assert (
            body["gap"]["current_state_id"] == body["current"]["state_id"]
        )
        assert body["gap"]["future_state_id"] == body["future"]["state_id"]

    def test_get_backcast_returns_the_bundle(self, client) -> None:
        goal = _create_goal(client)
        created = _define_backcast(client, goal["goal_id"])
        response = client.get(f"/goals/{goal['goal_id']}/backcast")
        assert response.status_code == 200
        assert response.json() == created

    def test_get_backcast_before_definition_is_404(self, client) -> None:
        goal = _create_goal(client)
        response = client.get(f"/goals/{goal['goal_id']}/backcast")
        assert response.status_code == 404
        assert "no backcast" in response.json()["detail"]

    def test_define_backcast_unknown_goal_is_404(self, client) -> None:
        response = client.post(
            f"/goals/{uuid.uuid4()}/backcast",
            json={
                "current_narrative": "Now",
                "future_description": "Then",
                "target_date": "2026-12-31T00:00:00+00:00",
            },
        )
        assert response.status_code == 404

    def test_second_backcast_is_409(self, client) -> None:
        goal = _create_goal(client)
        _define_backcast(client, goal["goal_id"])
        response = client.post(
            f"/goals/{goal['goal_id']}/backcast",
            json={
                "current_narrative": "Now",
                "future_description": "Then",
                "target_date": "2027-12-31T00:00:00+00:00",
            },
        )
        assert response.status_code == 409
        assert "one per goal" in response.json()["detail"]

    def test_past_target_date_is_422(self, client) -> None:
        goal = _create_goal(client)
        response = client.post(
            f"/goals/{goal['goal_id']}/backcast",
            json={
                "current_narrative": "Now",
                "future_description": "Then",
                "target_date": "2020-01-01T00:00:00+00:00",
            },
        )
        assert response.status_code == 422

    def test_naive_target_date_is_422(self, client) -> None:
        goal = _create_goal(client)
        response = client.post(
            f"/goals/{goal['goal_id']}/backcast",
            json={
                "current_narrative": "Now",
                "future_description": "Then",
                "target_date": "2026-12-31T00:00:00",
            },
        )
        assert response.status_code == 422

    def test_blank_future_description_is_422(self, client) -> None:
        goal = _create_goal(client)
        response = client.post(
            f"/goals/{goal['goal_id']}/backcast",
            json={
                "current_narrative": "Now",
                "future_description": "   ",
                "target_date": "2026-12-31T00:00:00+00:00",
            },
        )
        assert response.status_code == 422

    def test_backcasts_are_isolated_per_app(self) -> None:
        from fastapi.testclient import TestClient

        from backcasting.app import create_app

        with TestClient(create_app()) as first_client:
            goal = _create_goal(first_client)
            _define_backcast(first_client, goal["goal_id"])
        with TestClient(create_app()) as second_client:
            response = second_client.get(f"/goals/{goal['goal_id']}/backcast")
        assert response.status_code == 404


class TestContract:
    def test_openapi_documents_backcast_routes(self, client) -> None:
        schema = client.app.openapi()
        paths = schema["paths"]
        path = "/goals/{goal_id}/backcast"
        assert path in paths, f"missing contract path {path}"
        assert "post" in paths[path]
        assert "get" in paths[path]
