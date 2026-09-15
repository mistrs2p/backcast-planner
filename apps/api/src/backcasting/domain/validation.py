"""Cross-entity domain validation.

Per ``docs/09-AI-ARCHITECTURE.md`` — "The LLM proposes and reasons; the
Domain validates and enforces" — and ADR-002, deterministic domain services
are authoritative for validation. Each entity already enforces its own
invariants in its constructor; this module adds the *cross-entity* rules
that no single constructor can see, starting with a Goal's assembled
backcasting context.

Checks performed by :func:`validate_goal_context`:

- ``OWNER_MISMATCH`` — the Future/Current State must reference the Goal
  they are validated against.
- ``TARGET_PRECEDES_SNAPSHOT`` — the destination's target date must lie
  after the current-state snapshot's capture time: backcasting reasons
  backward from a destination that is in the future relative to observed
  reality.

The function returns every issue found (empty list = valid) so callers can
report them together; :func:`require_valid` turns a non-empty result into a
:class:`DomainValidationError`.
"""

from __future__ import annotations

from dataclasses import dataclass

from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import Goal

OWNER_MISMATCH = "owner_mismatch"
TARGET_PRECEDES_SNAPSHOT = "target_precedes_snapshot"


@dataclass(frozen=True)
class ValidationIssue:
    """A single cross-entity rule violation."""

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class DomainValidationError(ValueError):
    """Raised by :func:`require_valid` when issues were found."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = list(issues)
        super().__init__(
            "domain validation failed: " + "; ".join(str(i) for i in self.issues)
        )


def validate_goal_context(
    goal: Goal,
    future_state: FutureState,
    current_state: CurrentState | None = None,
) -> list[ValidationIssue]:
    """Validate a Goal's assembled backcasting context.

    Returns all issues found; an empty list means the context is valid.
    """
    if not isinstance(goal, Goal):
        raise TypeError("goal must be a Goal")
    if not isinstance(future_state, FutureState):
        raise TypeError("future_state must be a FutureState")
    if current_state is not None and not isinstance(current_state, CurrentState):
        raise TypeError("current_state must be a CurrentState or None")

    issues: list[ValidationIssue] = []
    if future_state.goal_id != goal.goal_id:
        issues.append(
            ValidationIssue(
                OWNER_MISMATCH,
                f"future state {future_state.state_id} references goal "
                f"{future_state.goal_id}, not {goal.goal_id}",
            )
        )
    if current_state is not None:
        if current_state.goal_id != goal.goal_id:
            issues.append(
                ValidationIssue(
                    OWNER_MISMATCH,
                    f"current state {current_state.state_id} references goal "
                    f"{current_state.goal_id}, not {goal.goal_id}",
                )
            )
        if current_state.captured_at >= future_state.target_date:
            issues.append(
                ValidationIssue(
                    TARGET_PRECEDES_SNAPSHOT,
                    f"target date {future_state.target_date.isoformat()} is not "
                    f"after the snapshot captured at "
                    f"{current_state.captured_at.isoformat()}",
                )
            )
    return issues


def require_valid(issues: list[ValidationIssue]) -> None:
    """Raise :class:`DomainValidationError` if ``issues`` is non-empty."""
    if issues:
        raise DomainValidationError(issues)
