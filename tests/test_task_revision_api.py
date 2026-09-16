"""Tests for task revision (TASK-112) — the Task UI's capability.

A task on a DRAFT plan is editable assembly-time: revise its title,
description, estimate, and deadline. The motivating gap: TASK-111
lets tasks be added without an estimate, but publishing refuses
unestimated tasks — revision is the only way such a plan can ever
publish. Revising a published plan's task is the replanning
ladder's LOCAL scope (docs/08) and stays out of this surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.backcast import BackcastService
from backcasting.application.goals import GoalNotFoundError
from backcasting.application.milestones import NoBackcastRunError
from backcasting.application.plans import (
    NoPlanError,
    NoTaskError,
    PlanNotDraftError,
    PlanService,
)
from backcasting.domain.goal import create_goal
from backcasting.domain.task import TaskError
from backcasting.infrastructure.memory import (
    InMemoryBackcastingRunRepository,
    InMemoryCurrentStateRepository,
    InMemoryFutureStateRepository,
    InMemoryGapRepository,
    InMemoryGoalRepository,
    InMemoryMilestoneRepository,
    InMemoryOutcomeRepository,
    InMemoryPlanRepository,
    InMemoryTaskRepository,
)

UTC = timezone.utc
TARGET = datetime(2027, 6, 1, tzinfo=UTC)


class Stack:
    """One wired set of repos + services, as create_app assembles
    them (shared goal, run, and milestone repositories)."""

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
        self.plans = PlanService(
            self.goals,
            self.runs,
            InMemoryPlanRepository(),
            InMemoryOutcomeRepository(),
            InMemoryTaskRepository(),
            self.milestones,
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


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backcasting.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _beginnable_goal(client) -> str:
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
    return goal["goal_id"]


def _draft_with_task(stack: Stack, **task_kwargs):
    """A goal whose DRAFT plan carries one task, plus the task."""
    goal = stack.goal()
    stack.backcast_goal(goal)
    stack.plans.begin_plan(goal_id=goal.goal_id)
    task = stack.plans.add_task(goal_id=goal.goal_id, **task_kwargs)
    return stack, goal, task


class TestReviseTask:
    def test_revise_title_and_description(self) -> None:
        stack, goal, task = _draft_with_task(
            Stack(), title="Long runs", description="old"
        )
        revised = stack.plans.revise_task(
            goal_id=goal.goal_id,
            task_id=task.task_id,
            title="Weekly long runs",
            description="build to 32km",
        )
        assert revised.title == "Weekly long runs"
        assert revised.description == "build to 32km"
        assert revised.duration == task.duration
        assert revised.updated_at >= task.updated_at
        assert stack.plans.get_plan(goal.goal_id).tasks == (revised,)

    def test_revise_adds_the_missing_estimate(self) -> None:
        stack, goal, task = _draft_with_task(Stack(), title="No estimate")
        assert task.duration is None
        revised = stack.plans.revise_task(
            goal_id=goal.goal_id, task_id=task.task_id, duration_hours=2.5
        )
        assert revised.duration == timedelta(hours=2.5)

    def test_revise_replaces_the_estimate(self) -> None:
        stack, goal, task = _draft_with_task(
            Stack(), title="Long runs", duration_hours=2
        )
        revised = stack.plans.revise_task(
            goal_id=goal.goal_id, task_id=task.task_id, duration_hours=3
        )
        assert revised.duration == timedelta(hours=3)

    def test_revise_sets_the_deadline(self) -> None:
        stack, goal, task = _draft_with_task(Stack(), title="Long runs")
        deadline = datetime(2027, 1, 1, tzinfo=UTC)
        revised = stack.plans.revise_task(
            goal_id=goal.goal_id, task_id=task.task_id, deadline=deadline
        )
        assert revised.deadline == deadline

    def test_omitted_fields_keep_their_value(self) -> None:
        stack, goal, task = _draft_with_task(
            Stack(), title="Long runs", duration_hours=2
        )
        revised = stack.plans.revise_task(
            goal_id=goal.goal_id, task_id=task.task_id, title="Renamed"
        )
        assert revised.description == task.description
        assert revised.duration == timedelta(hours=2)
        assert revised.deadline == task.deadline

    def test_revision_then_publish_computes_the_revised_workload(self) -> None:
        stack, goal, task = _draft_with_task(
            Stack(), title="Sketch", duration_hours=1
        )
        unestimated = stack.plans.add_task(
            goal_id=goal.goal_id, title="No estimate"
        )
        # revise both: replace an estimate, and land a missing one
        stack.plans.revise_task(
            goal_id=goal.goal_id, task_id=task.task_id, duration_hours=4
        )
        stack.plans.revise_task(
            goal_id=goal.goal_id,
            task_id=unestimated.task_id,
            duration_hours=1.5,
        )
        bundle = stack.plans.publish(goal.goal_id)
        assert bundle.plan.workload == timedelta(hours=5.5)

    def test_unknown_task_is_rejected(self) -> None:
        stack, goal, _ = _draft_with_task(Stack(), title="Long runs")
        with pytest.raises(NoTaskError, match="no task"):
            stack.plans.revise_task(
                goal_id=goal.goal_id, task_id=uuid.uuid4(), title="X"
            )

    def test_task_from_another_plan_is_rejected(self) -> None:
        stack, goal, _ = _draft_with_task(Stack(), title="Long runs")
        other, other_goal, other_task = _draft_with_task(
            Stack(), title="Other plan's task"
        )
        assert other_goal.goal_id != goal.goal_id
        with pytest.raises(NoTaskError):
            stack.plans.revise_task(
                goal_id=goal.goal_id,
                task_id=other_task.task_id,
                title="Stolen",
            )
        # the other plan's task is untouched
        assert (
            other.plans.get_plan(other_goal.goal_id).tasks[0].title
            == "Other plan's task"
        )

    def test_unknown_goal_is_rejected(self) -> None:
        with pytest.raises(GoalNotFoundError):
            Stack().plans.revise_task(
                goal_id=uuid.uuid4(), task_id=uuid.uuid4(), title="X"
            )

    def test_revision_without_a_plan_is_rejected(self) -> None:
        stack = Stack()
        goal = stack.goal()
        with pytest.raises(NoPlanError):
            stack.plans.revise_task(
                goal_id=goal.goal_id, task_id=uuid.uuid4(), title="X"
            )

    def test_revision_without_a_backcast_is_rejected(self) -> None:
        stack = Stack()
        goal = stack.goal()
        with pytest.raises(NoBackcastRunError):
            stack.plans.begin_plan(goal_id=goal.goal_id)
        with pytest.raises(NoPlanError):
            stack.plans.revise_task(
                goal_id=goal.goal_id, task_id=uuid.uuid4(), title="X"
            )

    def test_blank_title_is_rejected(self) -> None:
        stack, goal, task = _draft_with_task(Stack(), title="Long runs")
        with pytest.raises(TaskError, match="non-empty"):
            stack.plans.revise_task(
                goal_id=goal.goal_id, task_id=task.task_id, title="   "
            )

    def test_non_positive_duration_is_rejected(self) -> None:
        stack, goal, task = _draft_with_task(Stack(), title="Long runs")
        with pytest.raises(TaskError, match="strictly positive"):
            stack.plans.revise_task(
                goal_id=goal.goal_id,
                task_id=task.task_id,
                duration_hours=0,
            )

    def test_deadline_before_creation_is_rejected(self) -> None:
        stack, goal, task = _draft_with_task(Stack(), title="Long runs")
        with pytest.raises(TaskError, match="after created_at"):
            stack.plans.revise_task(
                goal_id=goal.goal_id,
                task_id=task.task_id,
                deadline=task.created_at - timedelta(days=1),
            )

    def test_revision_after_publish_is_rejected(self) -> None:
        stack, goal, task = _draft_with_task(
            Stack(), title="Long runs", duration_hours=2
        )
        stack.plans.publish(goal.goal_id)
        with pytest.raises(PlanNotDraftError):
            stack.plans.revise_task(
                goal_id=goal.goal_id, task_id=task.task_id, title="Too late"
            )


class TestReviseTaskHttp:
    def test_revise_over_http(self, client) -> None:

        goal_id = _beginnable_goal(client)
        client.post(f"/goals/{goal_id}/plan", json={})
        task = client.post(
            f"/goals/{goal_id}/plan/tasks", json={"title": "Sketch"}
        ).json()
        response = client.patch(
            f"/goals/{goal_id}/plan/tasks/{task['task_id']}",
            json={"title": "Sketch the flow", "duration_hours": 1.5},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == "Sketch the flow"
        assert body["duration_hours"] == 1.5
        # the revision is visible through the bundle
        bundle = client.get(f"/goals/{goal_id}/plan").json()
        assert bundle["tasks"][0]["title"] == "Sketch the flow"

    def test_revise_then_publish_over_http(self, client) -> None:

        goal_id = _beginnable_goal(client)
        client.post(f"/goals/{goal_id}/plan", json={})
        task = client.post(
            f"/goals/{goal_id}/plan/tasks", json={"title": "No estimate"}
        ).json()
        assert (
            client.post(f"/goals/{goal_id}/plan/publish").status_code == 422
        )
        revised = client.patch(
            f"/goals/{goal_id}/plan/tasks/{task['task_id']}",
            json={"duration_hours": 2},
        )
        assert revised.status_code == 200, revised.text
        published = client.post(f"/goals/{goal_id}/plan/publish")
        assert published.status_code == 200, published.text
        assert published.json()["plan"]["workload_hours"] == 2

    def test_unknown_task_is_404(self, client) -> None:

        goal_id = _beginnable_goal(client)
        client.post(f"/goals/{goal_id}/plan", json={})
        response = client.patch(
            f"/goals/{goal_id}/plan/tasks/{uuid.uuid4()}",
            json={"title": "Nowhere"},
        )
        assert response.status_code == 404
        assert "no task" in response.json()["detail"]

    def test_revision_without_plan_is_404(self, client) -> None:

        goal_id = _beginnable_goal(client)
        response = client.patch(
            f"/goals/{goal_id}/plan/tasks/{uuid.uuid4()}",
            json={"title": "Nowhere"},
        )
        assert response.status_code == 404

    def test_revision_after_publish_is_409(self, client) -> None:

        goal_id = _beginnable_goal(client)
        client.post(f"/goals/{goal_id}/plan", json={})
        task = client.post(
            f"/goals/{goal_id}/plan/tasks",
            json={"title": "Long runs", "duration_hours": 1},
        ).json()
        client.post(f"/goals/{goal_id}/plan/publish")
        response = client.patch(
            f"/goals/{goal_id}/plan/tasks/{task['task_id']}",
            json={"title": "Too late"},
        )
        assert response.status_code == 409

    def test_zero_duration_is_422(self, client) -> None:

        goal_id = _beginnable_goal(client)
        client.post(f"/goals/{goal_id}/plan", json={})
        task = client.post(
            f"/goals/{goal_id}/plan/tasks", json={"title": "Sketch"}
        ).json()
        response = client.patch(
            f"/goals/{goal_id}/plan/tasks/{task['task_id']}",
            json={"duration_hours": 0},
        )
        assert response.status_code == 422

    def test_naive_deadline_is_422(self, client) -> None:

        goal_id = _beginnable_goal(client)
        client.post(f"/goals/{goal_id}/plan", json={})
        task = client.post(
            f"/goals/{goal_id}/plan/tasks", json={"title": "Sketch"}
        ).json()
        response = client.patch(
            f"/goals/{goal_id}/plan/tasks/{task['task_id']}",
            json={"deadline": "2027-01-01T00:00:00"},
        )
        assert response.status_code == 422


class TestContract:
    def test_openapi_documents_task_revision(self, client) -> None:
        schema = client.app.openapi()
        path = "/goals/{goal_id}/plan/tasks/{task_id}"
        assert path in schema["paths"], f"missing contract path {path}"
        assert "patch" in schema["paths"][path]
