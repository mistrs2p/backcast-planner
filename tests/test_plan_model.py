"""Tests for the plan model (TASK-047).

Pins the Plan entity — the executable shape of a goal ("what must
happen and the workload required", docs/06) — its lifecycle
(``DRAFT/CANDIDATE → ACTIVE → SUPERSEDED/ARCHIVED/INVALID``, docs/03),
routine revision, and the "Goal max 1 Active Plan" rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import Goal, create_goal
from backcasting.domain.plan import (
    PLAN_TRANSITIONS,
    TERMINAL_PLAN_STATUSES,
    InvalidPlanTransition,
    Plan,
    PlanError,
    PlanStatus,
    active_plan,
    can_transition,
    create_plan,
    is_terminal,
    revise_plan,
    transition_plan,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
REVISED = datetime(2026, 1, 2, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def goal() -> Goal:
    return create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)


@pytest.fixture
def plan(goal: Goal) -> Plan:
    return create_plan(goal, 20 * HOUR, title="Focus week", created_at=CREATED)


class TestCreatePlan:
    def test_plan_starts_in_draft(self, goal: Goal) -> None:
        plan = create_plan(goal, 20 * HOUR, created_at=CREATED)
        assert plan.goal_id == goal.goal_id
        assert plan.status is PlanStatus.DRAFT
        assert plan.title == ""
        assert plan.run_id is None
        assert plan.created_at == CREATED
        assert plan.updated_at == CREATED

    def test_run_provenance_is_optional(self, goal: Goal) -> None:
        run_id = uuid.uuid4()
        plan = create_plan(
            goal, 20 * HOUR, run_id=run_id, created_at=CREATED
        )
        assert plan.run_id == run_id

    def test_rejects_non_goal(self) -> None:
        with pytest.raises(TypeError, match="goal must be a Goal"):
            create_plan("goal", 20 * HOUR)  # type: ignore[arg-type]

    def test_negative_workload_is_rejected(self, goal: Goal) -> None:
        with pytest.raises(PlanError, match="non-negative timedelta"):
            create_plan(goal, -HOUR)

    def test_zero_workload_is_allowed(self, goal: Goal) -> None:
        # A plan of pure delegation: nothing to schedule, still a plan.
        plan = create_plan(goal, timedelta(0), created_at=CREATED)
        assert plan.workload == timedelta(0)

    def test_title_is_bounded(self, goal: Goal) -> None:
        with pytest.raises(PlanError, match="at most 200"):
            create_plan(goal, 20 * HOUR, title="x" * 201)

    def test_title_defaults_to_empty(self, goal: Goal) -> None:
        plan = create_plan(
            goal, 20 * HOUR, title=None, created_at=CREATED
        )  # type: ignore[arg-type]
        assert plan.title == ""

    def test_non_uuid_ids_are_rejected(self, goal: Goal) -> None:
        with pytest.raises(PlanError, match="plan_id must be a UUID"):
            create_plan(goal, 20 * HOUR, plan_id="id")
        with pytest.raises(PlanError, match="run_id must be"):
            create_plan(goal, 20 * HOUR, run_id="run")

    def test_stamps_must_be_utc_and_ordered(self, goal: Goal) -> None:
        plan = create_plan(goal, 20 * HOUR, created_at=CREATED)
        with pytest.raises(PlanError, match="must not precede"):
            Plan(
                plan_id=plan.plan_id,
                goal_id=plan.goal_id,
                workload=plan.workload,
                created_at=CREATED,
                updated_at=CREATED - timedelta(seconds=1),
            )

    def test_bad_status_is_rejected(self, goal: Goal) -> None:
        with pytest.raises(PlanError, match="status must be a PlanStatus"):
            Plan(
                plan_id=uuid.uuid4(),
                goal_id=goal.goal_id,
                workload=HOUR,
                status="active",  # type: ignore[arg-type]
            )


class TestRevisePlan:
    def test_revision_moves_editable_fields(self, plan: Plan) -> None:
        revised = revise_plan(
            plan, title="Focus sprint", workload=25 * HOUR, updated_at=REVISED
        )
        assert revised.title == "Focus sprint"
        assert revised.workload == 25 * HOUR
        assert revised.updated_at == REVISED

    def test_revision_carries_identity(self, plan: Plan) -> None:
        revised = revise_plan(plan, title="New", updated_at=REVISED)
        assert revised.plan_id == plan.plan_id
        assert revised.goal_id == plan.goal_id
        assert revised.status == plan.status
        assert revised.run_id == plan.run_id
        assert revised.created_at == plan.created_at

    def test_untouched_fields_stay(self, plan: Plan) -> None:
        revised = revise_plan(plan, updated_at=REVISED)
        assert revised.title == plan.title
        assert revised.workload == plan.workload

    def test_invalid_workload_is_rejected(self, plan: Plan) -> None:
        with pytest.raises(PlanError, match="non-negative timedelta"):
            revise_plan(plan, workload=-HOUR, updated_at=REVISED)

    def test_rejects_non_plan(self) -> None:
        with pytest.raises(TypeError, match="plan must be a Plan"):
            revise_plan("plan", updated_at=REVISED)  # type: ignore[arg-type]


class TestLifecycle:
    def test_full_lifecycle_path(self, plan: Plan) -> None:
        candidate = transition_plan(plan, PlanStatus.CANDIDATE, at=REVISED)
        assert candidate.status is PlanStatus.CANDIDATE
        active = transition_plan(candidate, PlanStatus.ACTIVE, at=REVISED)
        assert active.status is PlanStatus.ACTIVE
        superseded = transition_plan(active, PlanStatus.SUPERSEDED, at=REVISED)
        assert superseded.status is PlanStatus.SUPERSEDED

    def test_active_can_be_invalidated_or_archived(self, plan: Plan) -> None:
        active = transition_plan(
            transition_plan(plan, PlanStatus.CANDIDATE, at=REVISED),
            PlanStatus.ACTIVE,
            at=REVISED,
        )
        for terminal in (PlanStatus.INVALID, PlanStatus.ARCHIVED):
            moved = transition_plan(active, terminal, at=REVISED)
            assert moved.status is terminal

    def test_pre_active_states_may_be_archived(self, plan: Plan) -> None:
        assert can_transition(plan, PlanStatus.ARCHIVED)
        candidate = transition_plan(plan, PlanStatus.CANDIDATE, at=REVISED)
        assert can_transition(candidate, PlanStatus.ARCHIVED)

    def test_draft_cannot_activate_directly(self, plan: Plan) -> None:
        # The spec lifecycle starts at DRAFT/CANDIDATE; only a complete
        # CANDIDATE may go ACTIVE.
        with pytest.raises(InvalidPlanTransition):
            transition_plan(plan, PlanStatus.ACTIVE, at=REVISED)

    def test_candidate_cannot_be_superseded(self, plan: Plan) -> None:
        candidate = transition_plan(plan, PlanStatus.CANDIDATE, at=REVISED)
        with pytest.raises(InvalidPlanTransition):
            transition_plan(candidate, PlanStatus.SUPERSEDED, at=REVISED)

    def test_terminal_states_have_no_exits(self, plan: Plan) -> None:
        active = transition_plan(
            transition_plan(plan, PlanStatus.CANDIDATE, at=REVISED),
            PlanStatus.ACTIVE,
            at=REVISED,
        )
        for terminal in TERMINAL_PLAN_STATUSES:
            assert is_terminal(terminal)
            ended = transition_plan(active, terminal, at=REVISED)
            with pytest.raises(InvalidPlanTransition):
                transition_plan(ended, PlanStatus.ACTIVE, at=REVISED)

    def test_same_status_transition_is_rejected(self, plan: Plan) -> None:
        with pytest.raises(InvalidPlanTransition):
            transition_plan(plan, PlanStatus.DRAFT, at=REVISED)

    def test_transitions_table_matches_spec(self) -> None:
        # docs/03: DRAFT/CANDIDATE -> ACTIVE -> SUPERSEDED/ARCHIVED/INVALID.
        assert PLAN_TRANSITIONS == {
            PlanStatus.DRAFT: frozenset(
                {PlanStatus.CANDIDATE, PlanStatus.ARCHIVED}
            ),
            PlanStatus.CANDIDATE: frozenset(
                {PlanStatus.ACTIVE, PlanStatus.ARCHIVED}
            ),
            PlanStatus.ACTIVE: frozenset(
                {
                    PlanStatus.SUPERSEDED,
                    PlanStatus.ARCHIVED,
                    PlanStatus.INVALID,
                }
            ),
            PlanStatus.SUPERSEDED: frozenset(),
            PlanStatus.ARCHIVED: frozenset(),
            PlanStatus.INVALID: frozenset(),
        }

    def test_invalid_transition_error_carries_statuses(self, plan: Plan) -> None:
        with pytest.raises(InvalidPlanTransition) as excinfo:
            transition_plan(plan, PlanStatus.ACTIVE, at=REVISED)
        assert excinfo.value.from_status is PlanStatus.DRAFT
        assert excinfo.value.to_status is PlanStatus.ACTIVE

    def test_transition_advances_updated_at_only(self, plan: Plan) -> None:
        moved = transition_plan(plan, PlanStatus.CANDIDATE, at=REVISED)
        assert moved.updated_at == REVISED
        assert moved.created_at == plan.created_at
        assert moved.plan_id == plan.plan_id
        assert moved.workload == plan.workload

    def test_bad_target_status_is_rejected(self, plan: Plan) -> None:
        with pytest.raises(PlanError, match="to_status must be a PlanStatus"):
            transition_plan(plan, "candidate", at=REVISED)  # type: ignore[arg-type]


class TestActivePlanRule:
    def _active(self, goal: Goal, **overrides) -> Plan:
        fields = dict(
            plan_id=uuid.uuid4(),
            goal_id=goal.goal_id,
            workload=HOUR,
            status=PlanStatus.ACTIVE,
            created_at=CREATED,
            updated_at=CREATED,
        )
        fields.update(overrides)
        return Plan(**fields)

    def test_returns_none_without_active(self, goal: Goal) -> None:
        assert active_plan((), goal.goal_id) is None

    def test_returns_the_active_plan(self, goal: Goal) -> None:
        active = self._active(goal)
        assert active_plan((active,), goal.goal_id) is active

    def test_ignores_other_goals_and_statuses(self, goal: Goal) -> None:
        other_goal = create_goal(uuid.uuid4(), "Other", created_at=CREATED)
        mine_draft = Plan(
            plan_id=uuid.uuid4(),
            goal_id=goal.goal_id,
            workload=HOUR,
            status=PlanStatus.DRAFT,
            created_at=CREATED,
            updated_at=CREATED,
        )
        theirs = self._active(other_goal)
        assert active_plan((mine_draft, theirs), goal.goal_id) is None
        assert active_plan((mine_draft, theirs), other_goal.goal_id) is theirs

    def test_multiple_active_plans_raise(self, goal: Goal) -> None:
        two = (self._active(goal), self._active(goal))
        with pytest.raises(PlanError, match="at most one"):
            active_plan(two, goal.goal_id)

    def test_non_tuple_plans_are_rejected(self, goal: Goal) -> None:
        with pytest.raises(PlanError, match="plans must be a tuple"):
            active_plan([], goal.goal_id)  # type: ignore[arg-type]

    def test_non_uuid_goal_id_is_rejected(self, goal: Goal) -> None:
        with pytest.raises(PlanError, match="goal_id must be a UUID"):
            active_plan((), "goal")  # type: ignore[arg-type]


class TestFactories:
    def test_injectable_id_and_clock(self, goal: Goal) -> None:
        plan_id = uuid.uuid4()
        plan = create_plan(
            goal,
            20 * HOUR,
            plan_id=plan_id,
            created_at=CREATED,
        )
        assert plan.plan_id == plan_id
        assert plan.created_at == CREATED
        assert plan.updated_at == CREATED
