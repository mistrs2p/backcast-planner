"""Tests for the task decomposition contract (TASK-054).

Pins pipeline step 12, "Generate tasks" (docs/04), behind ADR-002's
split: the LLM proposes (``TaskProposal``), the domain validates and
enforces (``accept_proposed_tasks``) — plan liveness, outcome
resolution by title, batch uniqueness.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.outcome import define_outcome
from backcasting.domain.plan import create_plan, transition_plan
from backcasting.domain.task import (
    TaskProposal,
    TaskError,
    accept_proposed_tasks,
    create_task,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
DEADLINE = datetime(2026, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


@pytest.fixture
def outcomes(plan):
    return (
        define_outcome(plan, "Guide published", created_at=CREATED),
        define_outcome(plan, "Team trained", created_at=CREATED),
    )


class TestTaskProposal:
    def test_minimal_proposal(self) -> None:
        proposal = TaskProposal(title="Write the guide")
        assert proposal.title == "Write the guide"
        assert proposal.description == ""
        assert proposal.duration is None
        assert proposal.deadline is None
        assert proposal.outcome_titles == ()

    def test_fields_are_stripped(self) -> None:
        proposal = TaskProposal(
            title="  Write the guide  ",
            outcome_titles=("  Guide published  ",),
        )
        assert proposal.title == "Write the guide"
        assert proposal.outcome_titles == ("Guide published",)

    def test_empty_title_is_rejected(self) -> None:
        for empty in ("", "   "):
            with pytest.raises(TaskError, match="non-empty"):
                TaskProposal(title=empty)

    def test_long_title_is_rejected(self) -> None:
        with pytest.raises(TaskError, match="at most 200"):
            TaskProposal(title="x" * 201)

    def test_zero_duration_is_rejected(self) -> None:
        with pytest.raises(TaskError, match="strictly positive"):
            TaskProposal(title="T", duration=timedelta(0))

    def test_naive_deadline_is_rejected(self) -> None:
        with pytest.raises(TaskError, match="deadline"):
            TaskProposal(title="T", deadline=datetime(2026, 3, 1))

    def test_bad_outcome_titles_are_rejected(self) -> None:
        with pytest.raises(TaskError, match="outcome_titles must be"):
            TaskProposal(title="T", outcome_titles="Guide published")  # type: ignore[arg-type]
        with pytest.raises(TaskError, match="non-empty strings"):
            TaskProposal(title="T", outcome_titles=("  ",))


class TestAcceptProposedTasks:
    def test_creates_tasks_in_proposal_order(self, plan, outcomes) -> None:
        proposals = (
            TaskProposal(title="Draft the guide"),
            TaskProposal(title="Run the training"),
        )
        tasks = accept_proposed_tasks(plan, outcomes, proposals, at=CREATED)
        assert [task.title for task in tasks] == ["Draft the guide", "Run the training"]
        assert all(task.plan_id == plan.plan_id for task in tasks)
        assert all(task.created_at == CREATED for task in tasks)

    def test_resolves_outcome_references(self, plan, outcomes) -> None:
        guide, trained = outcomes
        proposals = (
            TaskProposal(
                title="Draft the guide", outcome_titles=("Guide published",)
            ),
        )
        tasks = accept_proposed_tasks(plan, outcomes, proposals, at=CREATED)
        assert tasks[0].outcome_ids == frozenset({guide.outcome_id})
        assert trained.outcome_id not in tasks[0].outcome_ids

    def test_task_may_serve_several_outcomes(self, plan, outcomes) -> None:
        proposals = (
            TaskProposal(
                title="Launch day",
                outcome_titles=("Guide published", "Team trained"),
            ),
        )
        tasks = accept_proposed_tasks(plan, outcomes, proposals, at=CREATED)
        assert tasks[0].outcome_ids == frozenset(
            {outcome.outcome_id for outcome in outcomes}
        )

    def test_task_may_serve_no_outcome(self, plan, outcomes) -> None:
        # "Outcome may exist without Tasks" cuts both ways at
        # generation time: an unlinked task is allowed.
        proposals = (TaskProposal(title="Setup repo"),)
        tasks = accept_proposed_tasks(plan, outcomes, proposals, at=CREATED)
        assert tasks[0].outcome_ids == frozenset()

    def test_carries_duration_and_deadline(self, plan, outcomes) -> None:
        proposals = (
            TaskProposal(
                title="Draft the guide", duration=2 * HOUR, deadline=DEADLINE
            ),
        )
        tasks = accept_proposed_tasks(plan, outcomes, proposals, at=CREATED)
        assert tasks[0].duration == 2 * HOUR
        assert tasks[0].deadline == DEADLINE

    def test_empty_generation_is_rejected(self, plan, outcomes) -> None:
        with pytest.raises(TaskError, match="at least one task proposal"):
            accept_proposed_tasks(plan, outcomes, (), at=CREATED)

    def test_duplicate_task_titles_are_rejected(self, plan, outcomes) -> None:
        proposals = (
            TaskProposal(title="Draft the guide"),
            TaskProposal(title="Draft the guide"),
        )
        with pytest.raises(TaskError, match="duplicate task title"):
            accept_proposed_tasks(plan, outcomes, proposals, at=CREATED)

    def test_unknown_outcome_reference_is_rejected(self, plan, outcomes) -> None:
        proposals = (
            TaskProposal(title="T", outcome_titles=("Nonexistent",)),
        )
        with pytest.raises(TaskError, match="unknown outcome"):
            accept_proposed_tasks(plan, outcomes, proposals, at=CREATED)

    def test_foreign_plan_outcome_is_rejected(self, plan, outcomes) -> None:
        other_goal = create_goal(uuid.uuid4(), "Other", created_at=CREATED)
        other_plan = create_plan(other_goal, HOUR, created_at=CREATED)
        foreign = define_outcome(other_plan, "Elsewhere", created_at=CREATED)
        proposals = (TaskProposal(title="T"),)
        with pytest.raises(TaskError, match="does not belong"):
            accept_proposed_tasks(plan, (foreign,), proposals, at=CREATED)

    def test_ambiguous_outcome_titles_are_rejected(self, plan) -> None:
        twice = (
            define_outcome(plan, "Same title", created_at=CREATED),
            define_outcome(plan, "Same title", created_at=CREATED),
        )
        proposals = (TaskProposal(title="T"),)
        with pytest.raises(TaskError, match="duplicate outcome title"):
            accept_proposed_tasks(plan, twice, proposals, at=CREATED)

    def test_terminal_plan_cannot_gain_tasks(self, plan, outcomes) -> None:
        from backcasting.domain.plan import PlanStatus, revise_plan

        archived = transition_plan(
            revise_plan(plan, updated_at=CREATED), PlanStatus.ARCHIVED, at=CREATED
        )
        proposals = (TaskProposal(title="T"),)
        with pytest.raises(TaskError, match="cannot accept tasks"):
            accept_proposed_tasks(archived, outcomes, proposals, at=CREATED)

    def test_bad_arguments_are_rejected(self, plan, outcomes) -> None:
        proposals = (TaskProposal(title="T"),)
        with pytest.raises(TypeError, match="plan must be a Plan"):
            accept_proposed_tasks("plan", outcomes, proposals)  # type: ignore[arg-type]
        with pytest.raises(TaskError, match="outcomes must be a tuple"):
            accept_proposed_tasks(plan, list(outcomes), proposals)  # type: ignore[arg-type]
        with pytest.raises(TaskError, match="proposals must be a tuple"):
            accept_proposed_tasks(plan, outcomes, list(proposals))  # type: ignore[arg-type]
        with pytest.raises(TaskError, match="proposals must be TaskProposal"):
            accept_proposed_tasks(
                plan, outcomes, ("proposal",)  # type: ignore[arg-type]
            )


class TestDecompositionFlow:
    def test_proposals_then_estimation_then_workload(self, plan, outcomes) -> None:
        from backcasting.domain.task_estimation import (
            apply_estimation,
            estimate_workload,
            record_estimation,
        )

        proposals = (
            TaskProposal(title="Draft the guide", duration=2 * HOUR),
            TaskProposal(title="Run the training"),
        )
        tasks = accept_proposed_tasks(plan, outcomes, proposals, at=CREATED)
        estimation = record_estimation(
            tasks[1], 3 * HOUR, created_at=CREATED + timedelta(days=1)
        )
        tasks = (
            tasks[0],
            apply_estimation(tasks[1], estimation, updated_at=CREATED + timedelta(days=1)),
        )
        assert estimate_workload(tasks) == 5 * HOUR

    def test_manual_tasks_coexist_with_proposed(self, plan, outcomes) -> None:
        manual = create_task(plan, "Manual task", created_at=CREATED)
        proposed = accept_proposed_tasks(
            plan, outcomes, (TaskProposal(title="Proposed task"),), at=CREATED
        )
        titles = {manual.title, proposed[0].title}
        assert titles == {"Manual task", "Proposed task"}
