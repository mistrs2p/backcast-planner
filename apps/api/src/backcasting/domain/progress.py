"""Progress snapshots — the third term of the triad.

"Planned ≠ Actual ≠ Progress" (docs/07-PROGRESS-FEEDBACK.md): the
plan says how much work there should be, the executions say how much
work actually happened, and *progress* is the derived reading of
where the plan stands — captured here as an immutable, point-in-time
snapshot (the progress counterpart of
:mod:`~backcasting.domain.current_state`: reality observed repeatedly
as snapshots over time, never mutated).

Derivation rules, all mechanical:

- ``planned`` is the plan's workload (:func:`estimate_workload`) —
  an unestimated task makes it unknown, and the estimation error
  propagates rather than being silently understated;
- ``actual`` sums the recorded sittings that *ended* at or before
  ``taken_at`` — a sitting still in progress at the snapshot moment
  has not actually happened yet — and only for the tasks given;
- ``progress`` (and ``completion_rate``) are capped at 1.0: a plan
  cannot be more than done. Overruns are the variance layer's
  material (docs/07), not extra progress — the same separation that
  keeps :mod:`~backcasting.domain.execution` free of judgment;
- ``remaining`` is the un-done workload, floored at zero for the
  same reason.

A task counts as complete when its own actual workload has reached
its own duration; a plan with no tasks reports zero everywhere
(no tasks, no progress to report).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from backcasting.domain.execution import Execution
from backcasting.domain.plan import Plan
from backcasting.domain.task import Task
from backcasting.domain.task_estimation import estimate_workload
from backcasting.domain.timezone import UTC, require_utc


class ProgressError(ValueError):
    """Raised when a progress-snapshot invariant is violated."""


@dataclass(frozen=True)
class ProgressSnapshot:
    """One point-in-time reading of a plan's progress."""

    snapshot_id: uuid.UUID
    plan_id: uuid.UUID
    taken_at: datetime
    task_count: int
    completed_task_count: int
    planned: timedelta
    actual: timedelta
    remaining: timedelta
    progress: float
    completion_rate: float

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, uuid.UUID):
            raise ProgressError("snapshot_id must be a UUID")
        if not isinstance(self.plan_id, uuid.UUID):
            raise ProgressError("plan_id must be a UUID")
        require_utc("taken_at", self.taken_at, error=ProgressError)
        for name in ("task_count", "completed_task_count"):
            count = getattr(self, name)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ProgressError(f"{name} must be a non-negative integer")
        if self.completed_task_count > self.task_count:
            raise ProgressError("completed_task_count must not exceed task_count")
        for name in ("planned", "actual", "remaining"):
            amount = getattr(self, name)
            if not isinstance(amount, timedelta) or amount < timedelta(0):
                raise ProgressError(f"{name} must be a non-negative timedelta")
        for name in ("progress", "completion_rate"):
            fraction = getattr(self, name)
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                raise ProgressError(f"{name} must be a number")
            if not 0.0 <= fraction <= 1.0:
                raise ProgressError(f"{name} must be within [0, 1]")


def take_progress_snapshot(
    plan: Plan,
    tasks: tuple[Task, ...],
    executions: tuple[Execution, ...],
    *,
    at: datetime | None = None,
    snapshot_id: uuid.UUID | None = None,
) -> ProgressSnapshot:
    """Take one progress snapshot of ``plan`` at ``at`` (default: now).

    ``tasks`` are the plan's tasks (each must belong to the plan) and
    ``executions`` the recorded sittings — only those for these tasks,
    ended at or before ``at``, count as actual. Unestimated tasks
    propagate the estimation error: a plan whose workload is unknown
    has no derivable progress.
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    if not isinstance(tasks, tuple):
        raise ProgressError("tasks must be a tuple of Task")
    for task in tasks:
        if not isinstance(task, Task):
            raise ProgressError("tasks must be Task instances")
        if task.plan_id != plan.plan_id:
            raise ProgressError("task does not belong to this plan")
    if not isinstance(executions, tuple):
        raise ProgressError("executions must be a tuple of Execution")
    for execution in executions:
        if not isinstance(execution, Execution):
            raise ProgressError("executions must be Execution instances")

    taken_at = at if at is not None else datetime.now(UTC)
    require_utc("at", taken_at, error=ProgressError)

    planned = estimate_workload(tasks)

    task_ids = {task.task_id for task in tasks}
    per_task_actual: dict[uuid.UUID, timedelta] = {}
    for execution in executions:
        if execution.task_id in task_ids and execution.end <= taken_at:
            per_task_actual[execution.task_id] = (
                per_task_actual.get(execution.task_id, timedelta(0))
                + execution.duration
            )
    actual = sum(per_task_actual.values(), timedelta(0))

    completed = sum(
        1
        for task in tasks
        if per_task_actual.get(task.task_id, timedelta(0)) >= task.duration
    )

    if planned > timedelta(0):
        progress = min(actual, planned) / planned
    else:
        progress = 0.0
    completion_rate = completed / len(tasks) if tasks else 0.0
    remaining = planned - actual if planned > actual else timedelta(0)

    return ProgressSnapshot(
        snapshot_id=snapshot_id if snapshot_id is not None else uuid.uuid4(),
        plan_id=plan.plan_id,
        taken_at=taken_at,
        task_count=len(tasks),
        completed_task_count=completed,
        planned=planned,
        actual=actual,
        remaining=remaining,
        progress=progress,
        completion_rate=completion_rate,
    )
