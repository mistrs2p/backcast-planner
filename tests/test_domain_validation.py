"""Tests for cross-entity domain validation (TASK-017).

Covers validate_goal_context (ownership matching, target-after-snapshot)
and require_valid aggregation, per docs/09's "the Domain validates and
enforces" separation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.goal import create_goal
from backcasting.domain.validation import (
    OWNER_MISMATCH,
    TARGET_PRECEDES_SNAPSHOT,
    DomainValidationError,
    ValidationIssue,
    require_valid,
    validate_goal_context,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)


@pytest.fixture
def goal():
    return create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)


@pytest.fixture
def future_state(goal):
    return define_future_state(
        goal.goal_id, "Complete the city marathon.", TARGET, created_at=CREATED
    )


@pytest.fixture
def current_state(goal):
    return capture_current_state(
        goal.goal_id, "Can run 5 km comfortably.", captured_at=CAPTURED
    )


class TestValidateGoalContext:
    def test_matching_context_is_valid(
        self, goal, future_state, current_state
    ) -> None:
        assert validate_goal_context(goal, future_state, current_state) == []

    def test_context_without_current_state_is_valid(self, goal, future_state) -> None:
        assert validate_goal_context(goal, future_state, None) == []

    def test_future_state_owned_by_other_goal_is_flagged(
        self, goal, future_state, current_state
    ) -> None:
        other = define_future_state(
            uuid.uuid4(), "Different goal.", TARGET, created_at=CREATED
        )
        issues = validate_goal_context(goal, other, current_state)
        codes = [issue.code for issue in issues]
        assert OWNER_MISMATCH in codes
        assert TARGET_PRECEDES_SNAPSHOT not in codes

    def test_current_state_owned_by_other_goal_is_flagged(
        self, goal, future_state, current_state
    ) -> None:
        other = capture_current_state(
            uuid.uuid4(), "Different reality.", captured_at=CAPTURED
        )
        issues = validate_goal_context(goal, future_state, other)
        codes = [issue.code for issue in issues]
        assert OWNER_MISMATCH in codes
        assert TARGET_PRECEDES_SNAPSHOT not in codes

    def test_target_equal_to_snapshot_is_flagged(
        self, goal, current_state
    ) -> None:
        future_state = define_future_state(
            goal.goal_id, "Destination.", CAPTURED, created_at=CREATED
        )
        issues = validate_goal_context(goal, future_state, current_state)
        assert [issue.code for issue in issues] == [TARGET_PRECEDES_SNAPSHOT]

    def test_target_before_snapshot_is_flagged(self, goal, current_state) -> None:
        future_state = define_future_state(
            goal.goal_id,
            "Destination.",
            CAPTURED + timedelta(days=1),
            created_at=CREATED,
        )
        earlier = capture_current_state(
            goal.goal_id, "Later reality.", captured_at=CAPTURED + timedelta(days=2)
        )
        issues = validate_goal_context(goal, future_state, earlier)
        assert [issue.code for issue in issues] == [TARGET_PRECEDES_SNAPSHOT]

    def test_all_issues_are_reported_together(self, goal) -> None:
        other_goal_id = uuid.uuid4()
        future_state = define_future_state(
            other_goal_id, "Destination.", TARGET, created_at=CREATED
        )
        current_state = capture_current_state(
            other_goal_id, "Reality.", captured_at=TARGET + timedelta(days=1)
        )
        issues = validate_goal_context(goal, future_state, current_state)
        codes = [issue.code for issue in issues]
        assert codes.count(OWNER_MISMATCH) == 2
        assert TARGET_PRECEDES_SNAPSHOT in codes

    def test_issues_carry_human_readable_messages(
        self, goal, future_state, current_state
    ) -> None:
        other = capture_current_state(
            uuid.uuid4(), "Different reality.", captured_at=CAPTURED
        )
        issues = validate_goal_context(goal, future_state, other)
        assert all(issue.message for issue in issues)
        assert str(issues[0]).startswith(f"{OWNER_MISMATCH}:")

    @pytest.mark.parametrize(
        "bad_call",
        [
            lambda goal, fs, cs: validate_goal_context("goal", fs, cs),
            lambda goal, fs, cs: validate_goal_context(goal, "future", cs),
            lambda goal, fs, cs: validate_goal_context(goal, fs, "current"),
        ],
    )
    def test_wrong_types_raise_type_error(self, goal, future_state, current_state, bad_call) -> None:
        with pytest.raises(TypeError):
            bad_call(goal, future_state, current_state)


class TestRequireValid:
    def test_empty_issue_list_passes(self) -> None:
        require_valid([])

    def test_nonempty_issue_list_raises_with_all_issues(self) -> None:
        issues = [
            ValidationIssue("a", "first problem"),
            ValidationIssue("b", "second problem"),
        ]
        with pytest.raises(DomainValidationError) as excinfo:
            require_valid(issues)
        assert excinfo.value.issues == issues
        assert "first problem" in str(excinfo.value)
        assert "second problem" in str(excinfo.value)

    def test_raised_error_preserves_issue_list_copy(self) -> None:
        issues = [ValidationIssue("a", "problem")]
        try:
            require_valid(issues)
        except DomainValidationError as error:
            assert error.issues == issues
            error.issues.clear()
            assert issues  # original list untouched
