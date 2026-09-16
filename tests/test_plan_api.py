"""Tests for the plan API (TASK-111).

Covers the planning pipeline's tail as one capability: the
in-memory repositories, the ``PlanService`` use cases (begin from a
finished run, assemble outcomes and tasks on the draft, publish
with the computed workload), and the HTTP surface with its status
mapping (404/409/422).
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
    PlanAlreadyExistsError,
    PlanNotDraftError,
    PlanService,
)
from backcasting.domain.goal import create_goal
from backcasting.domain.outcome import OutcomeError
from backcasting.domain.plan import PlanStatus
from backcasting.domain.plan_generation import PlanGenerationError
from backcasting.domain.task import TaskError
from backcasting.domain.task_estimation import TaskEstimationError
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


class TestInMemoryPlanRepositories:
    def test_plans_list_for_goal_oldest_first(self) -> None:
        repo = InMemoryPlanRepository()
        goal = create_goal(uuid.uuid4(), "G")
        from backcasting.domain.plan import create_plan

        first = create_plan(
            goal, timedelta(1), created_at=datetime(2026, 6, 1, tzinfo=UTC)
        )
        second = create_plan(
            goal, timedelta(2), created_at=datetime(2026, 6, 2, tzinfo=UTC)
        )
        other = create_plan(
            create_goal(uuid.uuid4(), "Other"),
            timedelta(1),
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        repo.save(second)
        repo.save(first)
        repo.save(other)
        assert repo.list_for_goal(goal.goal_id) == (first, second)
        assert repo.get(first.plan_id) is first

    def test_outcomes_and_tasks_list_for_plan(self) -> None:
        from backcasting.domain.outcome import define_outcome
        from backcasting.domain.plan import create_plan
        from backcasting.domain.task import create_task

        goal = create_goal(uuid.uuid4(), "G")
        plan = create_plan(goal, timedelta(0))
        outcomes = InMemoryOutcomeRepository()
        tasks = InMemoryTaskRepository()
        first_outcome = define_outcome(
            plan, "First", created_at=datetime(2026, 6, 1, tzinfo=UTC)
        )
        second_outcome = define_outcome(
            plan, "Second", created_at=datetime(2026, 6, 2, tzinfo=UTC)
        )
        outcomes.save(second_outcome)
        outcomes.save(first_outcome)
        assert outcomes.list_for_plan(plan.plan_id) == (
            first_outcome,
            second_outcome,
        )
        first_task = create_task(
            plan,
            "A",
            duration=timedelta(hours=1),
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        second_task = create_task(
            plan,
            "B",
            duration=timedelta(hours=2),
            created_at=datetime(2026, 6, 2, tzinfo=UTC),
        )
        tasks.save(second_task)
        tasks.save(first_task)
        assert tasks.list_for_plan(plan.plan_id) == (first_task, second_task)


class TestPlanServiceBegin:
    def test_begin_finishes_the_run_and_opens_a_draft(self) -> None:
        stack = Stack()
        goal = stack.goal()
        bundle = stack.backcast_goal(goal)
        plan_view = stack.plans.begin_plan(goal_id=goal.goal_id)
        assert plan_view.plan.run_id == bundle.run.run_id
        assert plan_view.plan.status is PlanStatus.DRAFT
        assert plan_view.plan.workload == timedelta(0)
        assert plan_view.outcomes == ()
        assert plan_view.tasks == ()
        # the run the plan was born from is now COMPLETED
        assert stack.runs.latest_for_goal(goal.goal_id).status.value == (
            "completed"
        )

    def test_begin_unknown_goal_raises(self) -> None:
        with pytest.raises(GoalNotFoundError):
            Stack().plans.begin_plan(goal_id=uuid.uuid4())

    def test_begin_without_backcast_raises(self) -> None:
        stack = Stack()
        goal = stack.goal()
        with pytest.raises(NoBackcastRunError):
            stack.plans.begin_plan(goal_id=goal.goal_id)

    def test_second_plan_for_goal_is_rejected(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        stack.plans.begin_plan(goal_id=goal.goal_id)
        with pytest.raises(PlanAlreadyExistsError, match="one per goal"):
            stack.plans.begin_plan(goal_id=goal.goal_id)

    def test_get_plan_before_begin_is_none(self) -> None:
        stack = Stack()
        goal = stack.goal()
        assert stack.plans.get_plan(goal.goal_id) is None


class TestPlanServiceAssembly:
    def _draft(self):
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        stack.plans.begin_plan(goal_id=goal.goal_id)
        return stack, goal

    def test_add_outcome_binds_milestone(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        # milestones attach to a RUNNING run — pin before the plan
        # begins (beginning finishes the run)
        from backcasting.application.milestones import MilestoneService

        milestone = MilestoneService(
            stack.goals, stack.runs, stack.milestones
        ).define_milestone(
            goal_id=goal.goal_id,
            title="First 10k",
            target_date=datetime(2026, 12, 1, tzinfo=UTC),
        )
        stack.plans.begin_plan(goal_id=goal.goal_id)
        outcome = stack.plans.add_outcome(
            goal_id=goal.goal_id,
            title="Run 10k without stopping",
            milestone_id=milestone.milestone_id,
        )
        assert outcome.milestone_id == milestone.milestone_id
        assert stack.plans.get_plan(goal.goal_id).outcomes == (outcome,)

    def test_add_outcome_unknown_milestone_is_rejected(self) -> None:
        stack, goal = self._draft()
        with pytest.raises(ValueError, match="no milestone"):
            stack.plans.add_outcome(
                goal_id=goal.goal_id,
                title="Nowhere",
                milestone_id=uuid.uuid4(),
            )

    def test_add_task_with_duration_and_outcomes(self) -> None:
        stack, goal = self._draft()
        outcome = stack.plans.add_outcome(
            goal_id=goal.goal_id, title="Run 10k"
        )
        task = stack.plans.add_task(
            goal_id=goal.goal_id,
            title="Weekly long run",
            duration_hours=1.5,
            outcome_ids=(outcome.outcome_id,),
        )
        assert task.duration == timedelta(hours=1.5)
        assert task.outcome_ids == frozenset({outcome.outcome_id})

    def test_add_task_unknown_outcome_is_rejected(self) -> None:
        stack, goal = self._draft()
        with pytest.raises(PlanGenerationError, match="no outcome"):
            stack.plans.add_task(
                goal_id=goal.goal_id,
                title="Orphan",
                outcome_ids=(uuid.uuid4(),),
            )

    def test_add_outcome_without_plan_raises(self) -> None:
        stack = Stack()
        goal = stack.goal()
        with pytest.raises(NoPlanError):
            stack.plans.add_outcome(goal_id=goal.goal_id, title="No plan")

    def test_blank_outcome_title_is_rejected(self) -> None:
        stack, goal = self._draft()
        with pytest.raises(OutcomeError, match="non-empty"):
            stack.plans.add_outcome(goal_id=goal.goal_id, title="   ")

    def test_blank_task_title_is_rejected(self) -> None:
        stack, goal = self._draft()
        with pytest.raises(TaskError, match="non-empty"):
            stack.plans.add_task(goal_id=goal.goal_id, title="   ")


class TestPlanServicePublish:
    def _assembled(self):
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        stack.plans.begin_plan(goal_id=goal.goal_id)
        stack.plans.add_outcome(goal_id=goal.goal_id, title="Run 10k")
        stack.plans.add_task(
            goal_id=goal.goal_id, title="Long runs", duration_hours=2
        )
        stack.plans.add_task(
            goal_id=goal.goal_id, title="Tempo runs", duration_hours=1
        )
        return stack, goal

    def test_publish_computes_workload_and_freezes(self) -> None:
        stack, goal = self._assembled()
        bundle = stack.plans.publish(goal.goal_id)
        assert bundle.plan.status is PlanStatus.CANDIDATE
        assert bundle.plan.workload == timedelta(hours=3)
        assert len(bundle.tasks) == 2
        with pytest.raises(PlanNotDraftError):
            stack.plans.add_outcome(goal_id=goal.goal_id, title="Too late")
        with pytest.raises(PlanNotDraftError):
            stack.plans.publish(goal.goal_id)

    def test_publish_without_tasks_is_rejected(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        stack.plans.begin_plan(goal_id=goal.goal_id)
        with pytest.raises(PlanGenerationError, match="at least one task"):
            stack.plans.publish(goal.goal_id)

    def test_publish_with_unestimated_task_is_rejected(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        stack.plans.begin_plan(goal_id=goal.goal_id)
        stack.plans.add_task(goal_id=goal.goal_id, title="No estimate")
        with pytest.raises(TaskEstimationError, match="no estimate"):
            stack.plans.publish(goal.goal_id)

    def test_publish_with_unestimated_task_is_422_over_http(self, client) -> None:
        goal_id = _beginnable_goal(client)
        client.post(f"/goals/{goal_id}/plan", json={})
        client.post(f"/goals/{goal_id}/plan/tasks", json={"title": "No estimate"})
        response = client.post(f"/goals/{goal_id}/plan/publish")
        assert response.status_code == 422
        assert "no estimate" in response.json()["detail"]


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


class TestPlanHttpApi:
    def test_begin_and_get_plan(self, client) -> None:
        goal_id = _beginnable_goal(client)
        response = client.post(
            f"/goals/{goal_id}/plan", json={"title": "Marathon plan"}
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["plan"]["title"] == "Marathon plan"
        assert body["plan"]["status"] == "draft"
        assert body["plan"]["workload_hours"] == 0
        assert body["plan"]["run_id"]
        assert body["outcomes"] == []
        assert body["tasks"] == []
        got = client.get(f"/goals/{goal_id}/plan")
        assert got.status_code == 200
        assert got.json() == body

    def test_begin_unknown_goal_is_404(self, client) -> None:
        assert (
            client.post(f"/goals/{uuid.uuid4()}/plan", json={}).status_code
            == 404
        )

    def test_begin_without_backcast_is_404(self, client) -> None:
        goal = client.post(
            "/goals",
            json={"user_id": str(uuid.uuid4()), "title": "No backcast"},
        ).json()
        response = client.post(f"/goals/{goal['goal_id']}/plan", json={})
        assert response.status_code == 404

    def test_second_plan_is_409(self, client) -> None:
        goal_id = _beginnable_goal(client)
        assert (
            client.post(f"/goals/{goal_id}/plan", json={}).status_code == 201
        )
        response = client.post(f"/goals/{goal_id}/plan", json={})
        assert response.status_code == 409
        assert "one per goal" in response.json()["detail"]

    def test_get_plan_before_begin_is_404(self, client) -> None:
        goal_id = _beginnable_goal(client)
        response = client.get(f"/goals/{goal_id}/plan")
        assert response.status_code == 404
        assert "no plan" in response.json()["detail"]

    def test_assemble_and_publish_over_http(self, client) -> None:
        goal_id = _beginnable_goal(client)
        assert (
            client.post(f"/goals/{goal_id}/plan", json={}).status_code == 201
        )
        outcome = client.post(
            f"/goals/{goal_id}/plan/outcomes",
            json={"title": "Run 10k without stopping"},
        ).json()
        first = client.post(
            f"/goals/{goal_id}/plan/tasks",
            json={
                "title": "Long runs",
                "duration_hours": 2,
                "outcome_ids": [outcome["outcome_id"]],
            },
        )
        assert first.status_code == 201, first.text
        assert first.json()["duration_hours"] == 2
        assert first.json()["outcome_ids"] == [outcome["outcome_id"]]
        assert (
            client.post(
                f"/goals/{goal_id}/plan/tasks",
                json={"title": "Tempo runs", "duration_hours": 1},
            ).status_code
            == 201
        )
        published = client.post(f"/goals/{goal_id}/plan/publish")
        assert published.status_code == 200, published.text
        body = published.json()
        assert body["plan"]["status"] == "candidate"
        assert body["plan"]["workload_hours"] == 3
        # frozen after publishing
        late = client.post(
            f"/goals/{goal_id}/plan/outcomes", json={"title": "Too late"}
        )
        assert late.status_code == 409

    def test_publish_without_tasks_is_422(self, client) -> None:
        goal_id = _beginnable_goal(client)
        client.post(f"/goals/{goal_id}/plan", json={})
        response = client.post(f"/goals/{goal_id}/plan/publish")
        assert response.status_code == 422
        assert "at least one task" in response.json()["detail"]

    def test_negative_duration_is_422(self, client) -> None:
        goal_id = _beginnable_goal(client)
        client.post(f"/goals/{goal_id}/plan", json={})
        response = client.post(
            f"/goals/{goal_id}/plan/tasks",
            json={"title": "Negative", "duration_hours": -1},
        )
        assert response.status_code == 422

    def test_add_outcome_without_plan_is_404(self, client) -> None:
        goal_id = _beginnable_goal(client)
        response = client.post(
            f"/goals/{goal_id}/plan/outcomes", json={"title": "No plan"}
        )
        assert response.status_code == 404


class TestContract:
    def test_openapi_documents_plan_routes(self, client) -> None:
        schema = client.app.openapi()
        paths = schema["paths"]
        for path in (
            "/goals/{goal_id}/plan",
            "/goals/{goal_id}/plan/outcomes",
            "/goals/{goal_id}/plan/tasks",
            "/goals/{goal_id}/plan/publish",
        ):
            assert path in paths, f"missing contract path {path}"
