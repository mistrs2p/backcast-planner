"""Tests for the Goal domain model (TASK-012).

Covers ownership and identity invariants, title/description rules, the
lifecycle states defined by docs/03-DOMAIN-MODEL.md (states only —
transition rules arrive with the goal-lifecycle task), UTC timestamp
invariants, and the create/revise factories.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.goal import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    Goal,
    GoalError,
    GoalStatus,
    create_goal,
    revise_goal,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestGoalStatus:
    def test_states_match_domain_model_spec(self) -> None:
        assert [s.value for s in GoalStatus] == [
            "draft",
            "active",
            "paused",
            "completed",
            "cancelled",
            "archived",
        ]

    def test_status_is_string_serializable(self) -> None:
        assert GoalStatus.DRAFT.value == "draft"
        assert GoalStatus("active") is GoalStatus.ACTIVE


class TestGoal:
    def _valid_kwargs(self) -> dict:
        return {
            "goal_id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "title": "Run a marathon",
            "description": "Finish the city marathon in under 4 hours.",
            "status": GoalStatus.DRAFT,
            "created_at": CREATED,
            "updated_at": CREATED,
        }

    def test_valid_goal_round_trips(self) -> None:
        kwargs = self._valid_kwargs()
        goal = Goal(**kwargs)
        assert goal.goal_id == kwargs["goal_id"]
        assert goal.user_id == kwargs["user_id"]
        assert goal.title == "Run a marathon"
        assert goal.description == kwargs["description"]
        assert goal.status is GoalStatus.DRAFT

    def test_title_is_stripped(self) -> None:
        goal = Goal(**{**self._valid_kwargs(), "title": "  Run a marathon  "})
        assert goal.title == "Run a marathon"

    def test_goal_is_immutable(self) -> None:
        goal = Goal(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            goal.title = "something else"  # type: ignore[misc]

    def test_non_uuid_ids_are_rejected(self) -> None:
        with pytest.raises(GoalError):
            Goal(**{**self._valid_kwargs(), "goal_id": "not-a-uuid"})
        with pytest.raises(GoalError):
            Goal(**{**self._valid_kwargs(), "user_id": 42})

    @pytest.mark.parametrize("bad_title", ["", "   ", "x" * (MAX_TITLE_LENGTH + 1)])
    def test_invalid_titles_are_rejected(self, bad_title: str) -> None:
        with pytest.raises(GoalError):
            Goal(**{**self._valid_kwargs(), "title": bad_title})

    def test_overlong_description_is_rejected(self) -> None:
        with pytest.raises(GoalError):
            Goal(**{**self._valid_kwargs(), "description": "d" * (MAX_DESCRIPTION_LENGTH + 1)})

    def test_non_string_status_is_rejected(self) -> None:
        with pytest.raises(GoalError):
            Goal(**{**self._valid_kwargs(), "status": "active"})

    def test_naive_timestamps_are_rejected(self) -> None:
        with pytest.raises(GoalError):
            Goal(**{**self._valid_kwargs(), "created_at": datetime(2026, 1, 1)})
        with pytest.raises(GoalError):
            Goal(**{**self._valid_kwargs(), "updated_at": datetime(2026, 1, 1)})

    def test_non_utc_timestamps_are_rejected(self) -> None:
        # Europe/Berlin is UTC+1 on 2026-01-01.
        local = datetime(2026, 1, 1, 12, tzinfo=ZoneInfo("Europe/Berlin"))
        with pytest.raises(GoalError):
            Goal(**{**self._valid_kwargs(), "created_at": local})
        with pytest.raises(GoalError):
            Goal(**{**self._valid_kwargs(), "updated_at": local})

    def test_updated_before_created_is_rejected(self) -> None:
        with pytest.raises(GoalError):
            Goal(
                **{
                    **self._valid_kwargs(),
                    "updated_at": CREATED - timedelta(seconds=1),
                }
            )


class TestCreateGoal:
    def test_new_goal_starts_in_draft(self) -> None:
        goal = create_goal(uuid.uuid4(), "Learn piano")
        assert goal.status is GoalStatus.DRAFT
        assert goal.description == ""

    def test_generates_identity_and_timestamps(self) -> None:
        before = datetime.now(timezone.utc)
        goal = create_goal(uuid.uuid4(), "Learn piano")
        after = datetime.now(timezone.utc)
        assert isinstance(goal.goal_id, uuid.UUID)
        assert before <= goal.created_at <= after
        assert goal.created_at == goal.updated_at

    def test_injected_id_and_timestamp_are_honoured(self) -> None:
        goal_id = uuid.uuid4()
        goal = create_goal(
            uuid.uuid4(),
            "Learn piano",
            description="Jazz basics",
            goal_id=goal_id,
            created_at=CREATED,
        )
        assert goal.goal_id == goal_id
        assert goal.created_at == CREATED
        assert goal.updated_at == CREATED
        assert goal.description == "Jazz basics"

    def test_invalid_title_is_rejected(self) -> None:
        with pytest.raises(GoalError):
            create_goal(uuid.uuid4(), "   ")


class TestReviseGoal:
    def test_revision_changes_only_editable_fields(self) -> None:
        goal = create_goal(uuid.uuid4(), "Learn piano", created_at=CREATED)
        later = CREATED + timedelta(days=1)
        revised = revise_goal(goal, updated_at=later, title="Learn jazz piano")
        assert revised.goal_id == goal.goal_id
        assert revised.user_id == goal.user_id
        assert revised.status is goal.status
        assert revised.created_at == goal.created_at
        assert revised.title == "Learn jazz piano"
        assert revised.description == goal.description
        assert revised.updated_at == later

    def test_original_goal_is_unchanged(self) -> None:
        goal = create_goal(uuid.uuid4(), "Learn piano", created_at=CREATED)
        revise_goal(goal, updated_at=CREATED + timedelta(days=1), description="new")
        assert goal.description == ""

    def test_revision_revalidates_fields(self) -> None:
        goal = create_goal(uuid.uuid4(), "Learn piano", created_at=CREATED)
        with pytest.raises(GoalError):
            revise_goal(goal, updated_at=CREATED + timedelta(days=1), title="")

    def test_revision_timestamp_must_not_precede_creation(self) -> None:
        goal = create_goal(uuid.uuid4(), "Learn piano", created_at=CREATED)
        with pytest.raises(GoalError):
            revise_goal(goal, updated_at=CREATED - timedelta(seconds=1))
