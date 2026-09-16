"""Tests for manual replanning (TASK-115) — the Replanning UI's
capability.

docs/08's level 2 driven by hand on a plan past assembly: one task
revised in place (LOCAL — the archetypal re-estimate), the whole
plan re-derived (GLOBAL), and the version trail every meaningful
replan owes. A plan still in DRAFT is refused — assembly-time
editing (TASK-112) is the free edit; a replan is a *traced* change.
Regional scope stays out: the product does not surface the
dependency graph yet.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.backcast import BackcastService
from backcasting.application.goals import GoalNotFoundError
from backcasting.application.plans import (
    NoPlanError,
    NoTaskError,
    PlanService,
)
from backcasting.application.replanning import (
    PlanIsDraftError,
    ReplanningService,
)
from backcasting.domain.goal import create_goal
from backcasting.domain.local_replan import LocalReplanError
from backcasting.domain.plan_version import PlanVersionError
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
    InMemoryPlanVersionRepository,
    InMemoryTaskRepository,
)

UTC = timezone.utc
TARGET = datetime(2027, 6, 1, tzinfo=UTC)


class Stack:
    """One wired set of repos + services, as create_app assembles
    them (shared goal, plan, and task repositories)."""

    def __init__(self) -> None:
        self.goals = InMemoryGoalRepository()
        self.runs = InMemoryBackcastingRunRepository()
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
            InMemoryMilestoneRepository(),
        )
        self.tasks = self.plans._tasks
        self.replanning = ReplanningService(
            self.goals,
            self.plans._plans,
            self.tasks,
            InMemoryPlanVersionRepository(),
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

    def published_plan(self, durations=(3.0,)):
        """A goal with a published plan carrying one task per given
        duration, plus (goal, plan, tasks)."""
        goal = self.goal()
        self.backcast_goal(goal)
        self.plans.begin_plan(goal_id=goal.goal_id)
        tasks = [
            self.plans.add_task(
                goal_id=goal.goal_id,
                title=f"Task {index}",
                duration_hours=duration,
            )
            for index, duration in enumerate(durations)
        ]
        bundle = self.plans.publish(goal.goal_id)
        return goal, bundle.plan, tasks


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backcasting.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _published_goal(client, durations=(3.0,)) -> tuple[str, list[dict]]:
    """A goal (id) with a published plan over HTTP, plus its tasks."""
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
    response = client.post(f"/goals/{goal['goal_id']}/plan", json={})
    assert response.status_code == 201, response.text
    tasks = []
    for index, duration in enumerate(durations):
        response = client.post(
            f"/goals/{goal['goal_id']}/plan/tasks",
            json={"title": f"Task {index}", "duration_hours": duration},
        )
        assert response.status_code == 201, response.text
        tasks.append(response.json())
    response = client.post(f"/goals/{goal['goal_id']}/plan/publish")
    assert response.status_code == 200, response.text
    return goal["goal_id"], tasks


class TestVersionRepository:
    def test_versions_list_in_trail_order(self) -> None:
        repo = InMemoryPlanVersionRepository()
        from backcasting.domain.plan_version import PlanChangeSet

        def version(plan_id, number: int):
            return _version_record(
                repo,
                number,
                PlanChangeSet(revised_task_ids=(uuid.uuid4(),)),
                plan_id=plan_id,
            )

        plan_id = uuid.uuid4()
        second = version(plan_id, 2)
        first = version(plan_id, 1)
        assert repo.list_for_plan(first.plan_id) == (first, second)
        assert repo.list_for_plan(uuid.uuid4()) == ()
        assert repo.get(second.version_id) is second
        assert repo.get(uuid.uuid4()) is None

    def test_save_replaces_by_id(self) -> None:
        repo = InMemoryPlanVersionRepository()
        from backcasting.domain.plan_version import PlanChangeSet

        record = _version_record(
            repo, 1, PlanChangeSet(revised_task_ids=(uuid.uuid4(),))
        )
        replacement = _version_record(
            repo,
            1,
            PlanChangeSet(revised_task_ids=(uuid.uuid4(),)),
            version_id=record.version_id,
            plan_id=record.plan_id,
        )
        assert repo.list_for_plan(record.plan_id) == (replacement,)


def _version_record(
    repo, number, change_set, version_id=None, plan_id=None
):
    from backcasting.domain.plan_version import PlanVersion

    record = PlanVersion(
        version_id=version_id or uuid.uuid4(),
        plan_id=plan_id or uuid.uuid4(),
        version=number,
        reason=f"reason {number}",
        change_set=change_set,
        created_at=datetime(2026, 9, 16, 12, 0, tzinfo=UTC),
    )
    repo.save(record)
    return record


class TestLocalReplan:
    def test_re_estimate_shifts_workload_and_traces_version(self) -> None:
        stack = Stack()
        goal, plan, tasks = stack.published_plan(durations=(3.0,))
        bundle = stack.replanning.replan_task(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            reason="the estimate was wrong",
            duration_hours=5.0,
        )
        assert bundle.task.duration == timedelta(hours=5)
        assert bundle.plan.workload == timedelta(hours=5)
        assert bundle.version.reason == "the estimate was wrong"
        assert bundle.version.change_set.revised_task_ids == (
            tasks[0].task_id,
        )
        # persisted: the plan, task, and trail all moved
        assert stack.plans.get_plan(goal.goal_id).plan.workload == timedelta(
            hours=5
        )
        assert stack.replanning.list_versions(goal.goal_id) == (
            bundle.version,
        )

    def test_deadline_recommitment_traces_without_moving_workload(
        self,
    ) -> None:
        stack = Stack()
        goal, plan, tasks = stack.published_plan(durations=(3.0,))
        bundle = stack.replanning.replan_task(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            reason="pushed the deadline",
            deadline=datetime(2027, 3, 1, tzinfo=UTC),
        )
        assert bundle.plan.workload == timedelta(hours=3)
        assert bundle.version.change_set.workload is None

    def test_version_numbers_increase_along_the_trail(self) -> None:
        stack = Stack()
        goal, plan, tasks = stack.published_plan(durations=(3.0,))
        first = stack.replanning.replan_task(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            reason="first",
            duration_hours=4.0,
        )
        second = stack.replanning.replan_task(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            reason="second",
            duration_hours=5.0,
        )
        assert (first.version.version, second.version.version) == (1, 2)
        assert stack.replanning.list_versions(goal.goal_id) == (
            first.version,
            second.version,
        )

    def test_revision_that_changes_nothing_is_refused(self) -> None:
        stack = Stack()
        goal, plan, tasks = stack.published_plan(durations=(3.0,))
        with pytest.raises(LocalReplanError):
            stack.replanning.replan_task(
                goal_id=goal.goal_id,
                task_id=tasks[0].task_id,
                reason="nothing changes",
            )

    def test_draft_plan_is_refused(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        stack.plans.begin_plan(goal_id=goal.goal_id)
        task = stack.plans.add_task(
            goal_id=goal.goal_id, title="Task", duration_hours=1.0
        )
        with pytest.raises(PlanIsDraftError):
            stack.replanning.replan_task(
                goal_id=goal.goal_id,
                task_id=task.task_id,
                reason="too early",
                duration_hours=2.0,
            )

    def test_unknown_task(self) -> None:
        stack = Stack()
        goal, plan, _ = stack.published_plan()
        with pytest.raises(NoTaskError):
            stack.replanning.replan_task(
                goal_id=goal.goal_id,
                task_id=uuid.uuid4(),
                reason="no such task",
                duration_hours=2.0,
            )

    def test_task_from_another_plan(self) -> None:
        stack = Stack()
        goal, _, _ = stack.published_plan()
        other, _, other_tasks = stack.published_plan(durations=(2.0,))
        with pytest.raises(NoTaskError):
            stack.replanning.replan_task(
                goal_id=goal.goal_id,
                task_id=other_tasks[0].task_id,
                reason="wrong plan",
                duration_hours=4.0,
            )

    def test_unknown_goal_and_missing_plan(self) -> None:
        stack = Stack()
        with pytest.raises(GoalNotFoundError):
            stack.replanning.replan_task(
                goal_id=uuid.uuid4(),
                task_id=uuid.uuid4(),
                reason="no goal",
            )
        goal = stack.goal()
        with pytest.raises(NoPlanError):
            stack.replanning.list_versions(goal.goal_id)


class TestGlobalReplan:
    def test_recomputed_workload_and_new_title(self) -> None:
        stack = Stack()
        goal, plan, tasks = stack.published_plan(durations=(3.0, 2.0))
        bundle = stack.replanning.replan_globally(
            goal_id=goal.goal_id,
            reason="started over",
            title="Marathon, revised",
        )
        assert bundle.plan.workload == timedelta(hours=5)
        assert bundle.plan.title == "Marathon, revised"
        assert bundle.version.change_set.workload == timedelta(hours=5)

    def test_local_then_global_share_one_trail(self) -> None:
        stack = Stack()
        goal, plan, tasks = stack.published_plan(durations=(3.0, 2.0))
        local = stack.replanning.replan_task(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            reason="re-estimate",
            duration_hours=6.0,
        )
        assert local.plan.workload == timedelta(hours=8)
        # the re-derivation lands where the shifted plan stands —
        # same workload, same title — so it changed nothing and the
        # domain refuses it; the trail still records the local replan
        with pytest.raises(PlanVersionError):
            stack.replanning.replan_globally(
                goal_id=goal.goal_id, reason="started over"
            )
        assert stack.replanning.list_versions(goal.goal_id) == (
            local.version,
        )

    def test_global_replan_after_workload_shift(self) -> None:
        stack = Stack()
        goal, plan, tasks = stack.published_plan(durations=(3.0, 2.0))
        stack.replanning.replan_task(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            reason="re-estimate",
            duration_hours=6.0,
        )
        stack.replanning.replan_task(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            reason="shrink",
            duration_hours=1.0,
        )
        # the recomputation lands on the task set (1h + 2h), not on
        # the accumulated shifts; the new title is what makes the
        # re-derivation meaningful — the workload alone already
        # stands where the shifts left it
        bundle = stack.replanning.replan_globally(
            goal_id=goal.goal_id,
            reason="started over",
            title="Marathon, re-derived",
        )
        assert bundle.plan.workload == timedelta(hours=3)
        trail = stack.replanning.list_versions(goal.goal_id)
        assert [record.version for record in trail] == [1, 2, 3]

    def test_unestimated_task_set_refuses(self) -> None:
        stack = Stack()
        goal, plan, tasks = stack.published_plan(durations=(2.0, 3.0))
        # The state is unreachable through the application (publish
        # refuses unestimated plans, and revisions cannot clear an
        # estimate) — but the service must still surface the
        # domain's refusal rather than assume its inputs.
        unsized = replace(tasks[1], duration=None)
        stack.tasks.save(unsized)
        with pytest.raises(TaskEstimationError):
            stack.replanning.replan_globally(
                goal_id=goal.goal_id, reason="started over"
            )

    def test_draft_plan_is_refused(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        stack.plans.begin_plan(goal_id=goal.goal_id)
        stack.plans.add_task(
            goal_id=goal.goal_id, title="Task", duration_hours=1.0
        )
        with pytest.raises(PlanIsDraftError):
            stack.replanning.replan_globally(
                goal_id=goal.goal_id, reason="too early"
            )

    def test_reason_is_validated_by_the_domain(self) -> None:
        stack = Stack()
        goal, _, _ = stack.published_plan()
        with pytest.raises(PlanVersionError):
            stack.replanning.replan_globally(
                goal_id=goal.goal_id, reason="   "
            )


class TestReplanningHTTP:
    def test_local_replan_over_http(self, client) -> None:
        goal_id, tasks = _published_goal(client, durations=(3.0,))
        response = client.post(
            f"/goals/{goal_id}/plan/replan/local",
            json={
                "task_id": tasks[0]["task_id"],
                "reason": "the estimate was wrong",
                "duration_hours": 5.0,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["plan"]["workload_hours"] == 5.0
        assert body["task"]["duration_hours"] == 5.0
        assert body["version"]["reason"] == "the estimate was wrong"
        assert body["version"]["version"] == 1
        assert body["version"]["revised_task_ids"] == [
            tasks[0]["task_id"]
        ]

        # the plan reads shifted, and the trail carries the version
        plan = client.get(f"/goals/{goal_id}/plan").json()
        assert plan["plan"]["workload_hours"] == 5.0
        versions = client.get(f"/goals/{goal_id}/plan/versions").json()
        assert len(versions) == 1
        assert versions[0]["workload_hours"] == 5.0

    def test_global_replan_over_http(self, client) -> None:
        goal_id, tasks = _published_goal(client, durations=(3.0, 2.0))
        response = client.post(
            f"/goals/{goal_id}/plan/replan/global",
            json={"reason": "started over", "title": "Marathon, revised"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["plan"]["workload_hours"] == 5.0
        assert body["plan"]["title"] == "Marathon, revised"
        assert body["version"]["title"] == "Marathon, revised"

    def test_versions_empty_until_a_replan(self, client) -> None:
        goal_id, _ = _published_goal(client)
        response = client.get(f"/goals/{goal_id}/plan/versions")
        assert response.status_code == 200, response.text
        assert response.json() == []

    def test_draft_plan_conflict(self, client) -> None:
        goal = client.post(
            "/goals",
            json={"user_id": str(uuid.uuid4()), "title": "Run a marathon"},
        ).json()
        client.post(
            f"/goals/{goal['goal_id']}/backcast",
            json={
                "current_narrative": "Couch potato",
                "future_description": "Finish a marathon",
                "target_date": "2027-06-01T00:00:00+00:00",
            },
        )
        client.post(f"/goals/{goal['goal_id']}/plan", json={})
        response = client.post(
            f"/goals/{goal['goal_id']}/plan/replan/global",
            json={"reason": "too early"},
        )
        assert response.status_code == 409, response.text

    def test_not_founds(self, client) -> None:
        response = client.post(
            f"/goals/{uuid.uuid4()}/plan/replan/local",
            json={"task_id": str(uuid.uuid4()), "reason": "no goal"},
        )
        assert response.status_code == 404, response.text
        response = client.get(f"/goals/{uuid.uuid4()}/plan/versions")
        assert response.status_code == 404, response.text
        goal_id, tasks = _published_goal(client)
        response = client.post(
            f"/goals/{goal_id}/plan/replan/local",
            json={
                "task_id": str(uuid.uuid4()),
                "reason": "no such task",
            },
        )
        assert response.status_code == 404, response.text

    def test_no_change_is_unprocessable(self, client) -> None:
        goal_id, tasks = _published_goal(client)
        response = client.post(
            f"/goals/{goal_id}/plan/replan/local",
            json={"task_id": tasks[0]["task_id"], "reason": "nothing"},
        )
        assert response.status_code == 422, response.text

    def test_blank_reason_is_unprocessable(self, client) -> None:
        goal_id, _ = _published_goal(client)
        response = client.post(
            f"/goals/{goal_id}/plan/replan/global",
            json={"reason": ""},
        )
        assert response.status_code == 422, response.text

    def test_contract_paths(self) -> None:
        import json
        from pathlib import Path

        contract = json.loads(
            (
                Path(__file__).resolve().parent.parent
                / "packages"
                / "contracts"
                / "openapi.json"
            ).read_text(encoding="utf-8")
        )
        paths = contract["paths"]
        assert (
            "/goals/{goal_id}/plan/replan/local" in paths
        )
        assert (
            "/goals/{goal_id}/plan/replan/global" in paths
        )
        assert "/goals/{goal_id}/plan/versions" in paths
