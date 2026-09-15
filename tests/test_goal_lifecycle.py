"""Tests for the Goal lifecycle state machine (TASK-016).

Covers the transition table derived from docs/03-DOMAIN-MODEL.md
(DRAFT → ACTIVE → PAUSED → COMPLETED/CANCELLED/ARCHIVED), terminal-state
finality, and the transition/inspection helpers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import (
    GOAL_TRANSITIONS,
    TERMINAL_GOAL_STATUSES,
    Goal,
    GoalError,
    GoalStatus,
    InvalidGoalTransition,
    can_transition,
    create_goal,
    is_terminal,
    transition_goal,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
LATER = CREATED + timedelta(days=3)


def make_goal(status: GoalStatus) -> Goal:
    """A goal in the given status, bypassing the lifecycle for setup."""
    return Goal(
        goal_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Run a marathon",
        status=status,
        created_at=CREATED,
        updated_at=LATER,
    )


class TestTransitionTable:
    def test_draft_only_becomes_active(self) -> None:
        assert GOAL_TRANSITIONS[GoalStatus.DRAFT] == frozenset({GoalStatus.ACTIVE})

    def test_active_moves_to_paused_or_terminal(self) -> None:
        assert GOAL_TRANSITIONS[GoalStatus.ACTIVE] == frozenset(
            {
                GoalStatus.PAUSED,
                GoalStatus.COMPLETED,
                GoalStatus.CANCELLED,
                GoalStatus.ARCHIVED,
            }
        )

    def test_paused_resumes_or_terminates(self) -> None:
        assert GOAL_TRANSITIONS[GoalStatus.PAUSED] == frozenset(
            {
                GoalStatus.ACTIVE,
                GoalStatus.COMPLETED,
                GoalStatus.CANCELLED,
                GoalStatus.ARCHIVED,
            }
        )

    @pytest.mark.parametrize("status", sorted(TERMINAL_GOAL_STATUSES))
    def test_terminal_states_have_no_outgoing_transitions(
        self, status: GoalStatus
    ) -> None:
        assert GOAL_TRANSITIONS[status] == frozenset()

    def test_every_status_is_a_key(self) -> None:
        assert set(GOAL_TRANSITIONS) == set(GoalStatus)


class TestIsTerminal:
    @pytest.mark.parametrize(
        "status,fexpected",
        [
            (GoalStatus.DRAFT, False),
            (GoalStatus.ACTIVE, False),
            (GoalStatus.PAUSED, False),
            (GoalStatus.COMPLETED, True),
            (GoalStatus.CANCELLED, True),
            (GoalStatus.ARCHIVED, True),
        ],
    )
    def test_terminality(self, status: GoalStatus, fexpected: bool) -> None:
        assert is_terminal(status) is fexpected

    def test_non_status_is_rejected(self) -> None:
        with pytest.raises(GoalError):
            is_terminal("archived")  # type: ignore[arg-type]


class TestCanTransition:
    def test_legal_transition_is_allowed(self) -> None:
        goal = make_goal(GoalStatus.DRAFT)
        assert can_transition(goal, GoalStatus.ACTIVE) is True

    def test_illegal_transition_is_denied(self) -> None:
        goal = make_goal(GoalStatus.DRAFT)
        assert can_transition(goal, GoalStatus.COMPLETED) is False

    def test_same_status_is_denied(self) -> None:
        goal = make_goal(GoalStatus.ACTIVE)
        assert can_transition(goal, GoalStatus.ACTIVE) is False

    def test_non_status_is_rejected(self) -> None:
        goal = make_goal(GoalStatus.DRAFT)
        with pytest.raises(GoalError):
            can_transition(goal, "active")  # type: ignore[arg-type]


class TestTransitionGoal:
    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            (GoalStatus.DRAFT, GoalStatus.ACTIVE),
            (GoalStatus.ACTIVE, GoalStatus.PAUSED),
            (GoalStatus.ACTIVE, GoalStatus.COMPLETED),
            (GoalStatus.ACTIVE, GoalStatus.CANCELLED),
            (GoalStatus.ACTIVE, GoalStatus.ARCHIVED),
            (GoalStatus.PAUSED, GoalStatus.ACTIVE),
            (GoalStatus.PAUSED, GoalStatus.COMPLETED),
            (GoalStatus.PAUSED, GoalStatus.CANCELLED),
            (GoalStatus.PAUSED, GoalStatus.ARCHIVED),
        ],
    )
    def test_legal_transitions(
        self, from_status: GoalStatus, to_status: GoalStatus
    ) -> None:
        goal = make_goal(from_status)
        moved = transition_goal(goal, to_status, at=LATER + timedelta(days=1))
        assert moved.status is to_status
        assert moved.goal_id == goal.goal_id
        assert moved.user_id == goal.user_id
        assert moved.created_at == goal.created_at
        assert moved.title == goal.title
        assert moved.updated_at == LATER + timedelta(days=1)

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            (GoalStatus.DRAFT, GoalStatus.PAUSED),
            (GoalStatus.DRAFT, GoalStatus.COMPLETED),
            (GoalStatus.DRAFT, GoalStatus.CANCELLED),
            (GoalStatus.DRAFT, GoalStatus.ARCHIVED),
            (GoalStatus.DRAFT, GoalStatus.DRAFT),
            (GoalStatus.ACTIVE, GoalStatus.ACTIVE),
            (GoalStatus.ACTIVE, GoalStatus.DRAFT),
            (GoalStatus.PAUSED, GoalStatus.PAUSED),
            (GoalStatus.PAUSED, GoalStatus.DRAFT),
            (GoalStatus.COMPLETED, GoalStatus.ACTIVE),
            (GoalStatus.COMPLETED, GoalStatus.ARCHIVED),
            (GoalStatus.CANCELLED, GoalStatus.ACTIVE),
            (GoalStatus.CANCELLED, GoalStatus.ARCHIVED),
            (GoalStatus.ARCHIVED, GoalStatus.ACTIVE),
            (GoalStatus.ARCHIVED, GoalStatus.COMPLETED),
        ],
    )
    def test_illegal_transitions_raise(
        self, from_status: GoalStatus, to_status: GoalStatus
    ) -> None:
        goal = make_goal(from_status)
        with pytest.raises(InvalidGoalTransition) as excinfo:
            transition_goal(goal, to_status, at=LATER)
        assert excinfo.value.from_status is from_status
        assert excinfo.value.to_status is to_status

    def test_transition_defaults_to_now(self) -> None:
        goal = make_goal(GoalStatus.DRAFT)
        before = datetime.now(timezone.utc)
        moved = transition_goal(goal, GoalStatus.ACTIVE)
        after = datetime.now(timezone.utc)
        assert before <= moved.updated_at <= after

    def test_original_goal_is_unchanged(self) -> None:
        goal = make_goal(GoalStatus.DRAFT)
        transition_goal(goal, GoalStatus.ACTIVE, at=LATER)
        assert goal.status is GoalStatus.DRAFT

    def test_non_status_target_is_rejected(self) -> None:
        goal = make_goal(GoalStatus.DRAFT)
        with pytest.raises(GoalError):
            transition_goal(goal, "active", at=LATER)  # type: ignore[arg-type]

    def test_timestamp_must_not_precede_creation(self) -> None:
        goal = make_goal(GoalStatus.DRAFT)
        with pytest.raises(GoalError):
            transition_goal(
                goal, GoalStatus.ACTIVE, at=CREATED - timedelta(seconds=1)
            )

    def test_full_lifecycle_walk(self) -> None:
        goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
        goal = transition_goal(goal, GoalStatus.ACTIVE, at=CREATED + timedelta(days=1))
        goal = transition_goal(goal, GoalStatus.PAUSED, at=CREATED + timedelta(days=2))
        goal = transition_goal(goal, GoalStatus.ACTIVE, at=CREATED + timedelta(days=3))
        goal = transition_goal(
            goal, GoalStatus.COMPLETED, at=CREATED + timedelta(days=4)
        )
        assert goal.status is GoalStatus.COMPLETED
        assert is_terminal(goal.status)
        with pytest.raises(InvalidGoalTransition):
            transition_goal(goal, GoalStatus.ACTIVE, at=CREATED + timedelta(days=5))
