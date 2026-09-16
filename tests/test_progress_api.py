"""Tests for the progress API (TASK-114) — the Actual side of
docs/07's triad.

Covers the new ports and their in-memory implementations, the
``ProgressService`` use cases (record a sitting, take a snapshot,
read the latest), and the HTTP surface with its status mapping
(404/422). The derivation math itself is the domain's (TASK-071);
these tests pin the wiring and the read path the UI resolves from.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.backcast import BackcastService
from backcasting.application.goals import GoalNotFoundError
from backcasting.application.plans import PlanService
from backcasting.application.progress import (
    NoPlanError,
    NoTaskError,
    ProgressService,
)
from backcasting.domain.execution import Execution, ExecutionError
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.progress import (
    ProgressSnapshot,
    take_progress_snapshot,
)
from backcasting.domain.task_estimation import TaskEstimationError
from backcasting.infrastructure.memory import (
    InMemoryBackcastingRunRepository,
    InMemoryCurrentStateRepository,
    InMemoryExecutionRepository,
    InMemoryFutureStateRepository,
    InMemoryGapRepository,
    InMemoryGoalRepository,
    InMemoryMilestoneRepository,
    InMemoryOutcomeRepository,
    InMemoryPlanRepository,
    InMemoryProgressSnapshotRepository,
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
        self.plans = InMemoryPlanRepository()
        self.tasks = InMemoryTaskRepository()
        self.executions = InMemoryExecutionRepository()
        self.snapshots = InMemoryProgressSnapshotRepository()
        self.backcast = BackcastService(
            self.goals,
            InMemoryCurrentStateRepository(),
            InMemoryFutureStateRepository(),
            InMemoryGapRepository(),
            self.runs,
        )
        self.plan_service = PlanService(
            self.goals,
            self.runs,
            self.plans,
            InMemoryOutcomeRepository(),
            self.tasks,
            InMemoryMilestoneRepository(),
        )
        self.progress = ProgressService(
            self.goals, self.plans, self.tasks, self.executions, self.snapshots
        )

    def goal(self):
        goal = create_goal(uuid.uuid4(), "Run a marathon")
        self.goals.save(goal)
        return goal

    def published_plan(self, durations=(2.0, 1.0)):
        """A goal with a published plan of estimated tasks."""
        goal = self.goal()
        self.backcast.define_backcast(
            goal_id=goal.goal_id,
            current_narrative="Couch potato",
            future_description="Finish a marathon",
            target_date=TARGET,
        )
        self.plan_service.begin_plan(goal_id=goal.goal_id)
        tasks = [
            self.plan_service.add_task(
                goal_id=goal.goal_id, title=f"Task {i}", duration_hours=hours
            )
            for i, hours in enumerate(durations)
        ]
        self.plan_service.publish(goal.goal_id)
        return goal, tasks


class TestInMemoryProgressRepositories:
    def test_executions_list_for_task_earliest_first(self) -> None:
        repo = InMemoryExecutionRepository()
        task_id = uuid.uuid4()
        first = Execution(
            execution_id=uuid.uuid4(),
            task_id=task_id,
            start=datetime(2026, 6, 2, tzinfo=UTC),
            end=datetime(2026, 6, 2, 1, tzinfo=UTC),
            created_at=datetime(2026, 6, 2, tzinfo=UTC),
        )
        second = Execution(
            execution_id=uuid.uuid4(),
            task_id=task_id,
            start=datetime(2026, 6, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, 1, tzinfo=UTC),
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        other = Execution(
            execution_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            start=datetime(2026, 6, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, 1, tzinfo=UTC),
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        repo.save(first)
        repo.save(second)
        repo.save(other)
        assert repo.list_for_task(task_id) == (second, first)
        assert repo.get(first.execution_id) is first

    def test_snapshots_list_for_plan_earliest_taken_first(self) -> None:
        repo = InMemoryProgressSnapshotRepository()
        plan = create_plan(create_goal(uuid.uuid4(), "G"), timedelta(1))
        earlier = take_progress_snapshot(
            plan, (), (), at=datetime(2026, 6, 1, tzinfo=UTC)
        )
        later = take_progress_snapshot(
            plan, (), (), at=datetime(2026, 6, 2, tzinfo=UTC)
        )
        other_plan = create_plan(create_goal(uuid.uuid4(), "H"), timedelta(1))
        foreign = take_progress_snapshot(
            other_plan, (), (), at=datetime(2026, 6, 1, tzinfo=UTC)
        )
        repo.save(later)
        repo.save(earlier)
        repo.save(foreign)
        assert repo.list_for_plan(plan.plan_id) == (earlier, later)
        assert repo.get(earlier.snapshot_id) is earlier


class TestRecordExecution:
    def test_records_a_sitting(self) -> None:
        stack = Stack()
        goal, tasks = stack.published_plan()
        execution = stack.progress.record_execution(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            start=datetime(2026, 9, 16, 9, tzinfo=UTC),
            end=datetime(2026, 9, 16, 10, tzinfo=UTC),
        )
        assert execution.task_id == tasks[0].task_id
        assert execution.duration == timedelta(hours=1)
        assert stack.executions.list_for_task(tasks[0].task_id) == (
            execution,
        )

    def test_unknown_goal_is_rejected(self) -> None:
        with pytest.raises(GoalNotFoundError):
            Stack().progress.record_execution(
                goal_id=uuid.uuid4(),
                task_id=uuid.uuid4(),
                start=datetime(2026, 9, 16, 9, tzinfo=UTC),
                end=datetime(2026, 9, 16, 10, tzinfo=UTC),
            )

    def test_goal_without_plan_is_rejected(self) -> None:
        stack = Stack()
        goal = stack.goal()
        with pytest.raises(NoPlanError):
            stack.progress.record_execution(
                goal_id=goal.goal_id,
                task_id=uuid.uuid4(),
                start=datetime(2026, 9, 16, 9, tzinfo=UTC),
                end=datetime(2026, 9, 16, 10, tzinfo=UTC),
            )

    def test_task_from_another_plan_is_rejected(self) -> None:
        stack = Stack()
        goal, _ = stack.published_plan()
        other, other_tasks = stack.published_plan()
        with pytest.raises(NoTaskError, match="no task"):
            stack.progress.record_execution(
                goal_id=goal.goal_id,
                task_id=other_tasks[0].task_id,
                start=datetime(2026, 9, 16, 9, tzinfo=UTC),
                end=datetime(2026, 9, 16, 10, tzinfo=UTC),
            )

    def test_end_before_start_is_rejected(self) -> None:
        stack = Stack()
        goal, tasks = stack.published_plan()
        with pytest.raises(ExecutionError, match="after start"):
            stack.progress.record_execution(
                goal_id=goal.goal_id,
                task_id=tasks[0].task_id,
                start=datetime(2026, 9, 16, 10, tzinfo=UTC),
                end=datetime(2026, 9, 16, 9, tzinfo=UTC),
            )


class TestSnapshots:
    def test_snapshot_derives_progress_from_executions(self) -> None:
        stack = Stack()
        goal, tasks = stack.published_plan(durations=(2.0, 1.0))
        # sittings that ended in the past (only ended work counts):
        # one full sitting on the first task (2h of 2h → complete),
        # one partial on the second (0.5h of 1h)
        stack.progress.record_execution(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            start=datetime(2026, 9, 10, 9, tzinfo=UTC),
            end=datetime(2026, 9, 10, 11, tzinfo=UTC),
        )
        stack.progress.record_execution(
            goal_id=goal.goal_id,
            task_id=tasks[1].task_id,
            start=datetime(2026, 9, 10, 11, tzinfo=UTC),
            end=datetime(2026, 9, 10, 11, 30, tzinfo=UTC),
        )
        bundle = stack.progress.take_snapshot(goal.goal_id)
        snapshot = bundle.snapshot
        assert snapshot.task_count == 2
        assert snapshot.completed_task_count == 1
        assert snapshot.planned == timedelta(hours=3)
        assert snapshot.actual == timedelta(hours=2.5)
        assert snapshot.remaining == timedelta(minutes=30)
        assert snapshot.progress == pytest.approx(2.5 / 3)
        assert snapshot.completion_rate == pytest.approx(0.5)

    def test_sitting_in_progress_does_not_count_yet(self) -> None:
        stack = Stack()
        goal, tasks = stack.published_plan(durations=(1.0,))
        start = datetime.now(UTC) - timedelta(minutes=30)
        stack.progress.record_execution(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            start=start,
            end=start + timedelta(days=1),
        )
        bundle = stack.progress.take_snapshot(goal.goal_id)
        assert bundle.snapshot.actual == timedelta(0)

    def test_snapshots_append_to_history(self) -> None:
        stack = Stack()
        goal, _ = stack.published_plan(durations=(1.0,))
        first = stack.progress.take_snapshot(goal.goal_id).snapshot
        second = stack.progress.take_snapshot(goal.goal_id).snapshot
        history = stack.snapshots.list_for_plan(first.plan_id)
        # same-tick snapshots order by id (repo convention); the
        # service-level promise is the history holds them all and
        # the latest is one of them — strict ordering with injected
        # taken_at values is pinned at the repo layer above
        assert {s.snapshot_id for s in history} == {
            first.snapshot_id,
            second.snapshot_id,
        }
        latest = stack.progress.get_latest(goal.goal_id)
        assert latest.snapshot.snapshot_id in {
            first.snapshot_id,
            second.snapshot_id,
        }

    def test_latest_reflects_recorded_work(self) -> None:
        stack = Stack()
        goal, tasks = stack.published_plan(durations=(1.0,))
        empty = stack.progress.take_snapshot(goal.goal_id).snapshot
        assert empty.actual == timedelta(0)
        stack.progress.record_execution(
            goal_id=goal.goal_id,
            task_id=tasks[0].task_id,
            start=datetime(2026, 9, 10, 9, tzinfo=UTC),
            end=datetime(2026, 9, 10, 10, tzinfo=UTC),
        )
        latest = stack.progress.get_latest(goal.goal_id)
        # the persisted history only grows — the new reading needs a
        # new snapshot (taken after the work was recorded)
        assert latest.snapshot.actual == timedelta(0)
        worked = stack.progress.take_snapshot(goal.goal_id).snapshot
        assert worked.actual == timedelta(hours=1)
        assert worked.snapshot_id != empty.snapshot_id

    def test_get_latest_before_any_snapshot_is_none(self) -> None:
        stack = Stack()
        goal, _ = stack.published_plan()
        assert stack.progress.get_latest(goal.goal_id) is None

    def test_unestimated_task_blocks_the_snapshot(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast.define_backcast(
            goal_id=goal.goal_id,
            current_narrative="Couch potato",
            future_description="Finish a marathon",
            target_date=TARGET,
        )
        stack.plan_service.begin_plan(goal_id=goal.goal_id)
        stack.plan_service.add_task(goal_id=goal.goal_id, title="No estimate")
        with pytest.raises(TaskEstimationError, match="no estimate"):
            stack.progress.take_snapshot(goal.goal_id)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backcasting.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _goal_with_published_plan(client, durations=(2.0, 1.0)):
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
    client.post(f"/goals/{goal['goal_id']}/plan", json={})
    tasks = [
        client.post(
            f"/goals/{goal['goal_id']}/plan/tasks",
            json={"title": f"Task {i}", "duration_hours": hours},
        ).json()
        for i, hours in enumerate(durations)
    ]
    published = client.post(f"/goals/{goal['goal_id']}/plan/publish")
    assert published.status_code == 200, published.text
    return goal["goal_id"], tasks


class TestProgressHttpApi:
    def test_record_and_snapshot_over_http(self, client) -> None:
        goal_id, tasks = _goal_with_published_plan(client)
        recorded = client.post(
            f"/goals/{goal_id}/executions",
            json={
                "task_id": tasks[0]["task_id"],
                "start": "2026-09-15T09:00:00+00:00",
                "end": "2026-09-15T11:00:00+00:00",
            },
        )
        assert recorded.status_code == 201, recorded.text
        assert recorded.json()["task_id"] == tasks[0]["task_id"]
        snapshot = client.post(f"/goals/{goal_id}/progress")
        assert snapshot.status_code == 201, snapshot.text
        body = snapshot.json()
        assert body["task_count"] == 2
        assert body["completed_task_count"] == 1
        assert body["planned_hours"] == 3
        assert body["actual_hours"] == 2
        assert body["progress"] == pytest.approx(2 / 3)
        assert body["plan_status"] == "candidate"
        assert body["plan_workload_hours"] == 3
        # the latest snapshot is readable
        latest = client.get(f"/goals/{goal_id}/progress")
        assert latest.status_code == 200
        assert latest.json()["snapshot_id"] == body["snapshot_id"]

    def test_snapshot_before_any_is_404(self, client) -> None:
        goal_id, _ = _goal_with_published_plan(client)
        response = client.get(f"/goals/{goal_id}/progress")
        assert response.status_code == 404
        assert "no progress snapshot" in response.json()["detail"]

    def test_record_unknown_task_is_404(self, client) -> None:
        goal_id, _ = _goal_with_published_plan(client)
        response = client.post(
            f"/goals/{goal_id}/executions",
            json={
                "task_id": str(uuid.uuid4()),
                "start": "2026-09-16T09:00:00+00:00",
                "end": "2026-09-16T10:00:00+00:00",
            },
        )
        assert response.status_code == 404

    def test_record_without_plan_is_404(self, client) -> None:
        goal = client.post(
            "/goals",
            json={"user_id": str(uuid.uuid4()), "title": "No plan"},
        ).json()
        response = client.post(
            f"/goals/{goal['goal_id']}/executions",
            json={
                "task_id": str(uuid.uuid4()),
                "start": "2026-09-16T09:00:00+00:00",
                "end": "2026-09-16T10:00:00+00:00",
            },
        )
        assert response.status_code == 404

    def test_end_before_start_is_422(self, client) -> None:
        goal_id, tasks = _goal_with_published_plan(client)
        response = client.post(
            f"/goals/{goal_id}/executions",
            json={
                "task_id": tasks[0]["task_id"],
                "start": "2026-09-16T10:00:00+00:00",
                "end": "2026-09-16T09:00:00+00:00",
            },
        )
        assert response.status_code == 422

    def test_naive_datetimes_are_422(self, client) -> None:
        goal_id, tasks = _goal_with_published_plan(client)
        response = client.post(
            f"/goals/{goal_id}/executions",
            json={
                "task_id": tasks[0]["task_id"],
                "start": "2026-09-16T09:00:00",
                "end": "2026-09-16T10:00:00",
            },
        )
        assert response.status_code == 422

    def test_snapshot_over_unestimated_is_422(self, client) -> None:
        goal = client.post(
            "/goals",
            json={"user_id": str(uuid.uuid4()), "title": "Draft"},
        ).json()
        goal_id = goal["goal_id"]
        client.post(
            f"/goals/{goal_id}/backcast",
            json={
                "current_narrative": "x",
                "future_description": "y",
                "target_date": "2027-06-01T00:00:00+00:00",
            },
        )
        client.post(f"/goals/{goal_id}/plan", json={})
        client.post(f"/goals/{goal_id}/plan/tasks", json={"title": "No est"})
        response = client.post(f"/goals/{goal_id}/progress")
        assert response.status_code == 422
        assert "no estimate" in response.json()["detail"]


class TestContract:
    def test_openapi_documents_progress_routes(self, client) -> None:
        schema = client.app.openapi()
        paths = schema["paths"]
        for path in (
            "/goals/{goal_id}/executions",
            "/goals/{goal_id}/progress",
        ):
            assert path in paths, f"missing contract path {path}"
