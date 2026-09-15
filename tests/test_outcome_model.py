"""Tests for the outcome model (TASK-049).

Pins the "achieved state/result" (docs/02): plan-owned, optionally
milestone-bound, allowed to exist without tasks (docs/03).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.milestone import Milestone
from backcasting.domain.outcome import (
    Outcome,
    OutcomeError,
    define_outcome,
    revise_outcome,
)
from backcasting.domain.plan import create_plan

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
REVISED = datetime(2026, 1, 2, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


@pytest.fixture
def milestone(plan) -> Milestone:
    return Milestone(
        milestone_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        goal_id=plan.goal_id,
        title="Beta",
        target_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        created_at=CREATED,
        updated_at=CREATED,
    )


class TestDefineOutcome:
    def test_plan_level_outcome(self, plan) -> None:
        outcome = define_outcome(
            plan, "Beta released", description="Public beta.", created_at=CREATED
        )
        assert outcome.plan_id == plan.plan_id
        assert outcome.milestone_id is None
        assert outcome.title == "Beta released"
        assert outcome.description == "Public beta."
        assert outcome.created_at == CREATED

    def test_milestone_bound_outcome(self, plan, milestone) -> None:
        outcome = define_outcome(
            plan, "Beta released", milestone=milestone, created_at=CREATED
        )
        assert outcome.milestone_id == milestone.milestone_id

    def test_title_is_stripped(self, plan) -> None:
        outcome = define_outcome(plan, "  Beta released  ", created_at=CREATED)
        assert outcome.title == "Beta released"

    def test_empty_title_is_rejected(self, plan) -> None:
        for empty in ("", "   "):
            with pytest.raises(OutcomeError, match="non-empty"):
                define_outcome(plan, empty)

    def test_long_title_is_rejected(self, plan) -> None:
        with pytest.raises(OutcomeError, match="at most 200"):
            define_outcome(plan, "x" * 201)

    def test_long_description_is_rejected(self, plan) -> None:
        with pytest.raises(OutcomeError, match="at most 5000"):
            define_outcome(plan, "Title", description="x" * 5001)

    def test_description_defaults_to_empty(self, plan) -> None:
        outcome = define_outcome(
            plan, "Title", description=None, created_at=CREATED
        )  # type: ignore[arg-type]
        assert outcome.description == ""

    def test_non_uuid_ids_are_rejected(self, plan) -> None:
        with pytest.raises(OutcomeError, match="outcome_id must be a UUID"):
            define_outcome(plan, "Title", outcome_id="id")
        with pytest.raises(OutcomeError, match="milestone_id must be"):
            Outcome(
                outcome_id=uuid.uuid4(),
                plan_id=plan.plan_id,
                title="Title",
                milestone_id="milestone",  # type: ignore[arg-type]
            )

    def test_stamps_must_be_utc_and_ordered(self, plan) -> None:
        outcome = define_outcome(plan, "Title", created_at=CREATED)
        with pytest.raises(OutcomeError, match="must not precede"):
            Outcome(
                outcome_id=outcome.outcome_id,
                plan_id=outcome.plan_id,
                title="Title",
                created_at=CREATED,
                updated_at=CREATED - timedelta(seconds=1),
            )

    def test_rejects_non_plan(self) -> None:
        with pytest.raises(TypeError, match="plan must be a Plan"):
            define_outcome("plan", "Title")  # type: ignore[arg-type]

    def test_rejects_non_milestone(self, plan) -> None:
        with pytest.raises(TypeError, match="milestone must be"):
            define_outcome(
                plan, "Title", milestone="milestone"  # type: ignore[arg-type]
            )

    def test_injectable_id_and_clock(self, plan) -> None:
        outcome_id = uuid.uuid4()
        outcome = define_outcome(
            plan, "Title", outcome_id=outcome_id, created_at=CREATED
        )
        assert outcome.outcome_id == outcome_id
        assert outcome.updated_at == CREATED


class TestReviseOutcome:
    def test_revision_moves_descriptive_fields(self, plan) -> None:
        outcome = define_outcome(
            plan, "Beta released", description="Public beta.", created_at=CREATED
        )
        revised = revise_outcome(
            outcome,
            title="GA released",
            description="General availability.",
            updated_at=REVISED,
        )
        assert revised.title == "GA released"
        assert revised.description == "General availability."
        assert revised.updated_at == REVISED

    def test_revision_carries_identity_and_binding(self, plan, milestone) -> None:
        outcome = define_outcome(
            plan, "Beta released", milestone=milestone, created_at=CREATED
        )
        revised = revise_outcome(outcome, title="GA released", updated_at=REVISED)
        assert revised.outcome_id == outcome.outcome_id
        assert revised.plan_id == outcome.plan_id
        assert revised.milestone_id == milestone.milestone_id
        assert revised.created_at == outcome.created_at

    def test_untouched_fields_stay(self, plan) -> None:
        outcome = define_outcome(
            plan, "Beta released", description="Public beta.", created_at=CREATED
        )
        revised = revise_outcome(outcome, updated_at=REVISED)
        assert revised.title == outcome.title
        assert revised.description == outcome.description

    def test_invalid_title_is_rejected(self, plan) -> None:
        outcome = define_outcome(plan, "Title", created_at=CREATED)
        with pytest.raises(OutcomeError, match="non-empty"):
            revise_outcome(outcome, title="  ", updated_at=REVISED)

    def test_rejects_non_outcome(self) -> None:
        with pytest.raises(TypeError, match="outcome must be an Outcome"):
            revise_outcome("outcome", updated_at=REVISED)  # type: ignore[arg-type]
