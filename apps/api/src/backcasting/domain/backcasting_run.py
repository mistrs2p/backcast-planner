"""Backcasting run domain model.

A Backcasting Run records one execution of the backcasting pipeline
(``docs/04-BACKCASTING-MODEL.md``) for a Goal: which current-state
snapshot, destination, and gap it operated on, and how it ended. A goal
accumulates runs over time ("Goal 1:N Backcasting Runs",
``docs/03-DOMAIN-MODEL.md``) — replanning re-runs the same core engine
with a new Current State, producing a new run.

This module defines the run record and its outcome transitions. The
pipeline's orchestration (the 15 steps) is the backcasting-integration
concern, not the run's.

Rules:

- IDs are UUIDs; ``goal_id``/``current_state_id``/``future_state_id``/
  ``gap_id`` reference the inputs the run operated on.
- Lifecycle: a run starts RUNNING and ends exactly once — COMPLETED or
  FAILED. Terminal outcomes carry ``completed_at`` (UTC, ≥ ``started_at``).
- ``started_at`` is timezone-aware UTC.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum

from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.gap import Gap
from backcasting.domain.goal import Goal
from backcasting.domain.validation import require_valid, validate_goal_context


class BackcastingRunError(ValueError):
    """Raised when a BackcastingRun invariant is violated."""


class BackcastingRunStatus(str, Enum):
    """Outcome states of a backcasting run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_RUN_STATUSES = frozenset(
    {BackcastingRunStatus.COMPLETED, BackcastingRunStatus.FAILED}
)


@dataclass(frozen=True)
class BackcastingRun:
    """A recorded execution of the backcasting pipeline for a Goal."""

    run_id: uuid.UUID
    goal_id: uuid.UUID
    current_state_id: uuid.UUID
    future_state_id: uuid.UUID
    gap_id: uuid.UUID
    status: BackcastingRunStatus = BackcastingRunStatus.RUNNING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("run_id", "goal_id", "current_state_id", "future_state_id", "gap_id"):
            if not isinstance(getattr(self, name), uuid.UUID):
                raise BackcastingRunError(f"{name} must be a UUID")
        if not isinstance(self.status, BackcastingRunStatus):
            raise BackcastingRunError("status must be a BackcastingRunStatus")
        if not isinstance(self.started_at, datetime) or self.started_at.tzinfo is None:
            raise BackcastingRunError("started_at must be timezone-aware")
        if self.started_at.utcoffset() != timezone.utc.utcoffset(self.started_at):
            raise BackcastingRunError("started_at must be in UTC")
        if self.completed_at is not None:
            if not isinstance(self.completed_at, datetime) or (
                self.completed_at.tzinfo is None
            ):
                raise BackcastingRunError("completed_at must be timezone-aware")
            if self.completed_at.utcoffset() != timezone.utc.utcoffset(
                self.completed_at
            ):
                raise BackcastingRunError("completed_at must be in UTC")
            if self.completed_at < self.started_at:
                raise BackcastingRunError("completed_at must not precede started_at")
            if self.status not in TERMINAL_RUN_STATUSES:
                raise BackcastingRunError(
                    "completed_at is only allowed on terminal statuses"
                )
        elif self.status in TERMINAL_RUN_STATUSES:
            raise BackcastingRunError("terminal statuses require completed_at")


def start_run(
    goal: Goal,
    current_state: CurrentState,
    future_state: FutureState,
    gap: Gap,
    *,
    run_id: uuid.UUID | None = None,
    started_at: datetime | None = None,
) -> BackcastingRun:
    """Start a run over a validated, mutually consistent context.

    The goal context is validated first (ownership, target after
    snapshot), and the gap must be the one computed from exactly this
    current state and future state.
    """
    if not isinstance(goal, Goal):
        raise TypeError("goal must be a Goal")
    if not isinstance(current_state, CurrentState):
        raise TypeError("current_state must be a CurrentState")
    if not isinstance(future_state, FutureState):
        raise TypeError("future_state must be a FutureState")
    if not isinstance(gap, Gap):
        raise TypeError("gap must be a Gap")

    require_valid(validate_goal_context(goal, future_state, current_state))
    if gap.goal_id != goal.goal_id:
        raise BackcastingRunError("gap does not belong to this goal")
    if gap.current_state_id != current_state.state_id:
        raise BackcastingRunError("gap was not computed from this current state")
    if gap.future_state_id != future_state.state_id:
        raise BackcastingRunError("gap was not computed from this future state")

    return BackcastingRun(
        run_id=run_id if run_id is not None else uuid.uuid4(),
        goal_id=goal.goal_id,
        current_state_id=current_state.state_id,
        future_state_id=future_state.state_id,
        gap_id=gap.gap_id,
        status=BackcastingRunStatus.RUNNING,
        started_at=started_at if started_at is not None else datetime.now(timezone.utc),
    )


def _finish(
    run: BackcastingRun,
    status: BackcastingRunStatus,
    completed_at: datetime,
) -> BackcastingRun:
    if run.status in TERMINAL_RUN_STATUSES:
        raise BackcastingRunError(
            f"run already finished with status {run.status.value}"
        )
    return replace(run, status=status, completed_at=completed_at)


def complete_run(run: BackcastingRun, *, completed_at: datetime) -> BackcastingRun:
    """Return ``run`` moved to COMPLETED at ``completed_at`` (UTC)."""
    return _finish(run, BackcastingRunStatus.COMPLETED, completed_at)


def fail_run(run: BackcastingRun, *, completed_at: datetime) -> BackcastingRun:
    """Return ``run`` moved to FAILED at ``completed_at`` (UTC)."""
    return _finish(run, BackcastingRunStatus.FAILED, completed_at)
