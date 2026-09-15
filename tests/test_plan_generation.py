"""Tests for plan generation (TASK-055).

Pins the assembly half of the pipeline tail (docs/04): a DRAFT plan
opens from a COMPLETED run with provenance, and publishes into a
CANDIDATE only with tasks that all carry estimates — the workload is
computed, never asserted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.backcasting_run import complete_run, start_run
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.metric import Metric, MetricDirection, MetricKind
from backcasting.domain.outcome import define_outcome
from backcasting.domain.plan import PlanStatus
from backcasting.domain.plan_generation import (
    PlanGenerationError,
    begin_plan,
    generate_plan,
    publish_plan,
)
from backcasting.domain.task import TaskError, TaskProposal, create_task, revise_task

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
CALCULATED = datetime(2026, 1, 6, tzinfo=timezone.utc)
STARTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
FINISHED = STARTED + timedelta(minutes=5)
PUBLISHED = datetime(2026, 1, 7, tzinfo=timezone.utc)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)

DISTANCE = Metric("Distance", MetricKind.COUNT, MetricDirection.MAXIMIZE)


@pytest.fixture
def goal():
    return create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)


@pytest.fixture
def completed_run(goal):
    current = capture_current_state(
        goal.goal_id, "Can run 5 km.", captured_at=CAPTURED
    )
    future = define_future_state(
        goal.goal_id, "Complete the marathon.", TARGET, created_at=CREATED
    )
    gap = calculate_gap(
        goal,
        current,
        future,
        ((DISTANCE, 5, 42),),
        calculated_at=CALCULATED,
    )
    run = start_run(goal, current, future, gap, started_at=STARTED)
    return complete_run(run, completed_at=FINISHED)


@pytest.fixture
def draft(completed_run, goal):
    return begin_plan(completed_run, goal, title="Marathon plan", at=PUBLISHED)


def _tasks(draft, count=2):
    return tuple(
        revise_task(
            create_task(draft, f"Task {i}", created_at=PUBLISHED),
            duration=(i + 1) * HOUR,
            updated_at=PUBLISHED,
        )
        for i in range(count)
    )


class TestBeginPlan:
    def test_opens_a_draft_with_run_provenance(self, completed_run, goal) -> None:
        plan = begin_plan(completed_run, goal, title="Marathon plan", at=PUBLISHED)
        assert plan.status is PlanStatus.DRAFT
        assert plan.goal_id == goal.goal_id
        assert plan.run_id == completed_run.run_id
        assert plan.title == "Marathon plan"
        assert plan.workload == timedelta(0)

    def test_running_run_is_rejected(self, goal) -> None:
        current = capture_current_state(
            goal.goal_id, "Can run 5 km.", captured_at=CAPTURED
        )
        future = define_future_state(
            goal.goal_id, "Complete the marathon.", TARGET, created_at=CREATED
        )
        gap = calculate_gap(
            goal, current, future, ((DISTANCE, 5, 42),), calculated_at=CALCULATED
        )
        running = start_run(goal, current, future, gap, started_at=STARTED)
        with pytest.raises(PlanGenerationError, match="status running"):
            begin_plan(running, goal, at=PUBLISHED)

    def test_foreign_goal_is_rejected(self, completed_run) -> None:
        other = create_goal(uuid.uuid4(), "Other goal", created_at=CREATED)
        with pytest.raises(PlanGenerationError, match="does not belong"):
            begin_plan(completed_run, other, at=PUBLISHED)

    def test_rejects_bad_arguments(self, completed_run, goal) -> None:
        with pytest.raises(TypeError, match="run must be a BackcastingRun"):
            begin_plan("run", goal)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="goal must be a Goal"):
            begin_plan(completed_run, "goal")  # type: ignore[arg-type]


class TestPublishPlan:
    def test_publishes_into_candidate_with_computed_workload(self, draft) -> None:
        tasks = _tasks(draft)
        candidate = publish_plan(draft, tasks, at=PUBLISHED)
        assert candidate.status is PlanStatus.CANDIDATE
        assert candidate.workload == 3 * HOUR
        assert candidate.plan_id == draft.plan_id
        assert candidate.run_id == draft.run_id
        assert candidate.updated_at == PUBLISHED

    def test_draft_must_still_be_a_draft(self, draft) -> None:
        from backcasting.domain.plan import transition_plan

        candidate = transition_plan(draft, PlanStatus.CANDIDATE, at=PUBLISHED)
        with pytest.raises(PlanGenerationError, match="cannot publish"):
            publish_plan(candidate, _tasks(candidate), at=PUBLISHED)

    def test_empty_plan_is_rejected(self, draft) -> None:
        with pytest.raises(PlanGenerationError, match="at least one task"):
            publish_plan(draft, (), at=PUBLISHED)

    def test_unestimated_task_is_rejected(self, draft) -> None:
        from backcasting.domain.task_estimation import TaskEstimationError

        tasks = (create_task(draft, "No estimate", created_at=PUBLISHED),)
        with pytest.raises(TaskEstimationError, match="has no estimate"):
            publish_plan(draft, tasks, at=PUBLISHED)

    def test_foreign_task_is_rejected(self, draft, completed_run, goal) -> None:
        other_draft = begin_plan(completed_run, goal, at=PUBLISHED)
        foreign = revise_task(
            create_task(other_draft, "Elsewhere", created_at=PUBLISHED),
            duration=HOUR,
            updated_at=PUBLISHED,
        )
        with pytest.raises(PlanGenerationError, match="does not belong"):
            publish_plan(draft, (foreign,), at=PUBLISHED)

    def test_rejects_bad_arguments(self, draft) -> None:
        with pytest.raises(TypeError, match="plan must be a Plan"):
            publish_plan("plan", (), at=PUBLISHED)  # type: ignore[arg-type]
        with pytest.raises(PlanGenerationError, match="tasks must be a tuple"):
            publish_plan(draft, [], at=PUBLISHED)  # type: ignore[arg-type]


class TestGeneratePlan:
    def _proposals(self):
        return (
            TaskProposal(title="Long runs", duration=2 * HOUR),
            TaskProposal(title="Tempo runs", duration=HOUR),
        )

    def test_composes_accept_and_publish(self, draft) -> None:
        outcome = define_outcome(draft, "Race completed", created_at=PUBLISHED)
        plan = generate_plan(
            draft,
            (outcome,),
            self._proposals(),
            at=PUBLISHED,
        )
        assert plan.status is PlanStatus.CANDIDATE
        assert plan.workload == 3 * HOUR
        assert plan.run_id == draft.run_id
        assert plan.plan_id == draft.plan_id

    def test_proposal_rules_flow_through(self, draft) -> None:
        outcome = define_outcome(draft, "Race completed", created_at=PUBLISHED)
        proposals = (
            TaskProposal(title="Long runs"),
            TaskProposal(title="Long runs"),
        )
        with pytest.raises(TaskError, match="duplicate task title"):
            generate_plan(draft, (outcome,), proposals, at=PUBLISHED)

    def test_draft_keeps_run_provenance(self, completed_run, goal) -> None:
        draft = begin_plan(completed_run, goal, title="Marathon plan", at=PUBLISHED)
        outcome = define_outcome(draft, "Race completed", created_at=PUBLISHED)
        plan = generate_plan(draft, (outcome,), self._proposals(), at=PUBLISHED)
        assert plan.run_id == completed_run.run_id
        assert plan.title == "Marathon plan"

    def test_rejects_non_plan(self) -> None:
        with pytest.raises(TypeError, match="draft must be a Plan"):
            generate_plan("plan", (), (), at=PUBLISHED)  # type: ignore[arg-type]


class TestLifecycleWiring:
    def test_candidate_can_reach_active(self, draft) -> None:
        from backcasting.domain.plan import transition_plan

        candidate = publish_plan(draft, _tasks(draft), at=PUBLISHED)
        active = transition_plan(candidate, PlanStatus.ACTIVE, at=PUBLISHED)
        assert active.status is PlanStatus.ACTIVE

    def test_workload_feeds_feasibility(self, draft) -> None:
        from backcasting.domain.feasibility import evaluate_feasibility

        candidate = publish_plan(draft, _tasks(draft), at=PUBLISHED)
        result = evaluate_feasibility(
            candidate.workload, timedelta(0), usable_capacity=4 * HOUR
        )
        assert result.feasible
