"""Tests for the milestone API (TASK-110).

Milestones attach to a RUNNING backcasting run: the in-memory
repositories (run ordering, milestone ordering), the
``MilestoneService`` use cases, and the HTTP surface with its
status mapping (404/422).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.backcast import BackcastService
from backcasting.application.goals import GoalNotFoundError
from backcasting.application.milestones import (
    MilestoneService,
    NoBackcastRunError,
)
from backcasting.domain.backcasting_run import (
    BackcastingRun,
    BackcastingRunStatus,
)
from backcasting.domain.goal import create_goal
from backcasting.domain.milestone import MilestoneError
from backcasting.infrastructure.memory import (
    InMemoryBackcastingRunRepository,
    InMemoryCurrentStateRepository,
    InMemoryFutureStateRepository,
    InMemoryGapRepository,
    InMemoryGoalRepository,
    InMemoryMilestoneRepository,
)

UTC = timezone.utc
TARGET = datetime(2027, 6, 1, tzinfo=UTC)


class Stack:
    """One wired set of repos + services, as create_app assembles
    them (shared goal and run repositories)."""

    def __init__(self) -> None:
        self.goals = InMemoryGoalRepository()
        self.runs = InMemoryBackcastingRunRepository()
        self.milestones = InMemoryMilestoneRepository()
        self.backcast = BackcastService(
            self.goals,
            InMemoryCurrentStateRepository(),
            InMemoryFutureStateRepository(),
            InMemoryGapRepository(),
            self.runs,
        )
        self.milestone = MilestoneService(
            self.goals, self.runs, self.milestones
        )

    def goal(self):
        goal = create_goal(uuid.uuid4(), "Run a marathon")
        self.goals.save(goal)
        return goal

    def backcast_goal(self, goal):
        return self.backcast.define_backcast(
            goal_id=goal.goal_id,
            current_narrative="Couch potato",
            future_description="Finish a marathon",
            target_date=TARGET,
        )


class TestInMemoryRunAndMilestoneRepositories:
    def test_runs_list_latest_for_goal(self) -> None:
        repo = InMemoryBackcastingRunRepository()
        goal_id = uuid.uuid4()
        first = BackcastingRun(
            run_id=uuid.uuid4(),
            goal_id=goal_id,
            current_state_id=uuid.uuid4(),
            future_state_id=uuid.uuid4(),
            gap_id=uuid.uuid4(),
            started_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        second = BackcastingRun(
            run_id=uuid.uuid4(),
            goal_id=goal_id,
            current_state_id=uuid.uuid4(),
            future_state_id=uuid.uuid4(),
            gap_id=uuid.uuid4(),
            started_at=datetime(2026, 6, 2, tzinfo=UTC),
        )
        repo.save(first)
        repo.save(second)
        assert repo.list_for_goal(goal_id) == (first, second)
        assert repo.latest_for_goal(goal_id) is second
        assert repo.get(first.run_id) is first
        assert repo.latest_for_goal(uuid.uuid4()) is None

    def test_milestones_list_for_run_earliest_target_first(self) -> None:
        repo = InMemoryMilestoneRepository()
        run_id = uuid.uuid4()
        goal_id = uuid.uuid4()
        late = _milestone(run_id, goal_id, "Late", datetime(2027, 6, 2, tzinfo=UTC))
        early = _milestone(run_id, goal_id, "Early", datetime(2027, 6, 1, tzinfo=UTC))
        elsewhere = _milestone(
            uuid.uuid4(), goal_id, "Elsewhere", datetime(2027, 5, 1, tzinfo=UTC)
        )
        repo.save(late)
        repo.save(early)
        repo.save(elsewhere)
        assert repo.list_for_run(run_id) == (early, late)
        assert repo.get(early.milestone_id) is early


def _milestone(run_id, goal_id, title, target_date):
    from backcasting.domain.milestone import Milestone

    now = datetime(2026, 6, 1, tzinfo=UTC)
    return Milestone(
        milestone_id=uuid.uuid4(),
        run_id=run_id,
        goal_id=goal_id,
        title=title,
        target_date=target_date,
        created_at=now,
        updated_at=now,
    )


class TestMilestoneService:
    def test_define_milestone_attaches_to_the_run(self) -> None:
        stack = Stack()
        goal = stack.goal()
        bundle = stack.backcast_goal(goal)
        milestone = stack.milestone.define_milestone(
            goal_id=goal.goal_id,
            title="First 10k",
            target_date=datetime(2026, 10, 1, tzinfo=UTC),
            description="Race distance covered",
        )
        assert milestone.run_id == bundle.run.run_id
        assert milestone.goal_id == goal.goal_id
        assert stack.milestone.list_for_goal(goal.goal_id) == (milestone,)

    def test_list_is_ordered_earliest_target_first(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        late = stack.milestone.define_milestone(
            goal_id=goal.goal_id,
            title="Late",
            target_date=datetime(2027, 1, 1, tzinfo=UTC),
        )
        early = stack.milestone.define_milestone(
            goal_id=goal.goal_id,
            title="Early",
            target_date=datetime(2026, 10, 1, tzinfo=UTC),
        )
        assert stack.milestone.list_for_goal(goal.goal_id) == (early, late)

    def test_unknown_goal_raises(self) -> None:
        with pytest.raises(GoalNotFoundError):
            Stack().milestone.define_milestone(
                goal_id=uuid.uuid4(),
                title="Nowhere",
                target_date=TARGET,
            )

    def test_goal_without_backcast_raises(self) -> None:
        stack = Stack()
        goal = stack.goal()
        with pytest.raises(NoBackcastRunError, match="no backcasting run"):
            stack.milestone.define_milestone(
                goal_id=goal.goal_id,
                title="No run yet",
                target_date=TARGET,
            )

    def test_list_without_backcast_is_empty(self) -> None:
        stack = Stack()
        goal = stack.goal()
        assert stack.milestone.list_for_goal(goal.goal_id) == ()

    def test_blank_title_is_rejected(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        with pytest.raises(MilestoneError, match="non-empty"):
            stack.milestone.define_milestone(
                goal_id=goal.goal_id,
                title="   ",
                target_date=TARGET,
            )

    def test_past_target_date_is_rejected(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        with pytest.raises(MilestoneError, match="after"):
            stack.milestone.define_milestone(
                goal_id=goal.goal_id,
                title="Backwards",
                target_date=datetime(2020, 1, 1, tzinfo=UTC),
            )

    def test_finished_run_rejects_new_milestones(self) -> None:
        stack = Stack()
        goal = stack.goal()
        bundle = stack.backcast_goal(goal)
        finished = BackcastingRun(
            run_id=bundle.run.run_id,
            goal_id=bundle.run.goal_id,
            current_state_id=bundle.run.current_state_id,
            future_state_id=bundle.run.future_state_id,
            gap_id=bundle.run.gap_id,
            status=BackcastingRunStatus.COMPLETED,
            started_at=bundle.run.started_at,
            completed_at=bundle.run.started_at + timedelta(hours=1),
        )
        stack.runs.save(finished)
        with pytest.raises(MilestoneError, match="status completed"):
            stack.milestone.define_milestone(
                goal_id=goal.goal_id,
                title="Too late",
                target_date=TARGET,
            )


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backcasting.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _backcast_goal(client) -> dict:
    goal = client.post(
        "/goals",
        json={"user_id": str(uuid.uuid4()), "title": "Run a marathon"},
    ).json()
    response = client.post(
        f"/goals/{goal['goal_id']}/backcast",
        json={
            "current_narrative": "Couch potato",
            "future_description": "Finish a marathon",
            "target_date": "2027-06-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["run"]["status"] == "running"
    return goal


class TestMilestoneHttpApi:
    def test_define_milestone(self, client) -> None:
        goal = _backcast_goal(client)
        response = client.post(
            f"/goals/{goal['goal_id']}/milestones",
            json={
                "title": "First 10k",
                "target_date": "2026-10-01T00:00:00+00:00",
                "description": "Race distance covered",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["title"] == "First 10k"
        assert body["description"] == "Race distance covered"
        assert body["goal_id"] == goal["goal_id"]
        assert uuid.UUID(body["milestone_id"])

    def test_list_milestones_earliest_first(self, client) -> None:
        goal = _backcast_goal(client)
        base = f"/goals/{goal['goal_id']}/milestones"
        for title, date in (
            ("Late", "2027-01-01T00:00:00+00:00"),
            ("Early", "2026-10-01T00:00:00+00:00"),
        ):
            assert client.post(
                base, json={"title": title, "target_date": date}
            ).status_code == 201
        body = client.get(base).json()
        assert [m["title"] for m in body] == ["Early", "Late"]

    def test_list_before_backcast_is_empty(self, client) -> None:
        goal = client.post(
            "/goals",
            json={"user_id": str(uuid.uuid4()), "title": "No backcast"},
        ).json()
        response = client.get(f"/goals/{goal['goal_id']}/milestones")
        assert response.status_code == 200
        assert response.json() == []

    def test_define_unknown_goal_is_404(self, client) -> None:
        response = client.post(
            f"/goals/{uuid.uuid4()}/milestones",
            json={
                "title": "Nowhere",
                "target_date": "2026-10-01T00:00:00+00:00",
            },
        )
        assert response.status_code == 404

    def test_define_without_backcast_is_404(self, client) -> None:
        goal = client.post(
            "/goals",
            json={"user_id": str(uuid.uuid4()), "title": "No backcast"},
        ).json()
        response = client.post(
            f"/goals/{goal['goal_id']}/milestones",
            json={
                "title": "No run",
                "target_date": "2026-10-01T00:00:00+00:00",
            },
        )
        assert response.status_code == 404
        assert "no backcasting run" in response.json()["detail"]

    def test_blank_title_is_422(self, client) -> None:
        goal = _backcast_goal(client)
        response = client.post(
            f"/goals/{goal['goal_id']}/milestones",
            json={
                "title": "   ",
                "target_date": "2026-10-01T00:00:00+00:00",
            },
        )
        assert response.status_code == 422

    def test_past_target_date_is_422(self, client) -> None:
        goal = _backcast_goal(client)
        response = client.post(
            f"/goals/{goal['goal_id']}/milestones",
            json={
                "title": "Backwards",
                "target_date": "2020-01-01T00:00:00+00:00",
            },
        )
        assert response.status_code == 422

    def test_naive_target_date_is_422(self, client) -> None:
        goal = _backcast_goal(client)
        response = client.post(
            f"/goals/{goal['goal_id']}/milestones",
            json={"title": "Naive", "target_date": "2026-10-01T00:00:00"},
        )
        assert response.status_code == 422

    def test_backcast_response_includes_the_run(self, client) -> None:
        goal = _backcast_goal(client)
        bundle = client.get(f"/goals/{goal['goal_id']}/backcast").json()
        run = bundle["run"]
        assert run["status"] == "running"
        assert run["goal_id"] == goal["goal_id"]
        assert run["current_state_id"] == bundle["current"]["state_id"]
        assert run["future_state_id"] == bundle["future"]["state_id"]
        assert run["gap_id"] == bundle["gap"]["gap_id"]
        assert run["completed_at"] is None


class TestContract:
    def test_openapi_documents_milestone_routes(self, client) -> None:
        schema = client.app.openapi()
        paths = schema["paths"]
        path = "/goals/{goal_id}/milestones"
        assert path in paths, f"missing contract path {path}"
        assert "post" in paths[path]
        assert "get" in paths[path]
