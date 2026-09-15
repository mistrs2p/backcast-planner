"""Execution — what actually happened on a task.

"Execution: what actually happened" (docs/02-CONCEPTUAL-MODEL.md);
"Task 1:N Executions" (docs/03-DOMAIN-MODEL.md) — a task executes
in as many sittings as it really takes, each recorded as one
Execution. The mirror image of Schedule (the placement, the plan):
same interval shape, opposite epistemology.

"Planned ≠ Actual ≠ Progress" (docs/07-PROGRESS-FEEDBACK.md) is the
rule that shapes this model. An Execution is a *fact*, not a plan
and not a judgment:

- No deadline enforcement. Reality missing a deadline is exactly the
  signal the variance layer measures; refusing to record it would
  erase the deviation the product exists to surface.
- No granularity rounding. Work took what it took; snapping actuals
  to the 15-minute planning quantum (docs/05) is a planning concern.
- No consistency demands against the task's Schedules. Executing
  outside the placed time is a schedule variance (docs/07), recorded
  by the simple act of both records existing.

:func:`actual_duration` sums sittings into the Actual of the
planned-actual-progress triad — the counterpart of
:func:`~backcasting.domain.task_estimation.estimate_workload`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from backcasting.domain.task import Task
from backcasting.domain.timezone import UTC, require_utc


class ExecutionError(ValueError):
    """Raised when an execution invariant is violated."""


@dataclass(frozen=True)
class Execution:
    """One sitting of actual work: the half-open ``[start, end)``."""

    execution_id: uuid.UUID
    task_id: uuid.UUID
    start: datetime
    end: datetime
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.execution_id, uuid.UUID):
            raise ExecutionError("execution_id must be a UUID")
        if not isinstance(self.task_id, uuid.UUID):
            raise ExecutionError("task_id must be a UUID")
        require_utc("start", self.start, error=ExecutionError)
        require_utc("end", self.end, error=ExecutionError)
        if self.end <= self.start:
            raise ExecutionError("end must be after start")
        require_utc("created_at", self.created_at, error=ExecutionError)

    @property
    def duration(self) -> timedelta:
        """How long the sitting lasted."""
        return self.end - self.start


def create_execution(
    task: Task,
    start: datetime,
    end: datetime,
    *,
    execution_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Execution:
    """Record one sitting of actual work on ``task``.

    The interval is recorded as given — no deadline check, no
    rounding: an Execution is the Actual of docs/07's triad, and
    deviations from the plan are the variance layer's material, not
    this factory's refusal.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    return Execution(
        execution_id=execution_id if execution_id is not None else uuid.uuid4(),
        task_id=task.task_id,
        start=start,
        end=end,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def executions_for_task(
    executions: tuple[Execution, ...],
    task_id: uuid.UUID,
) -> tuple[Execution, ...]:
    """The sittings belonging to one task, in input order."""
    if not isinstance(task_id, uuid.UUID):
        raise ExecutionError("task_id must be a UUID")
    if not isinstance(executions, tuple):
        raise ExecutionError("executions must be a tuple of Execution")
    for execution in executions:
        if not isinstance(execution, Execution):
            raise ExecutionError("executions must be Execution instances")
    return tuple(execution for execution in executions if execution.task_id == task_id)


def actual_duration(executions: tuple[Execution, ...]) -> timedelta:
    """Sum the sittings — the Actual of the planned-actual triad.

    The empty sum is zero: a task not yet worked on has actually
    taken nothing (which is not the same as taking none — absence of
    a record is the fact, and progress interpretation is upstream).
    """
    if not isinstance(executions, tuple):
        raise ExecutionError("executions must be a tuple of Execution")
    for execution in executions:
        if not isinstance(execution, Execution):
            raise ExecutionError("executions must be Execution instances")
    return sum(
        (execution.end - execution.start for execution in executions),
        timedelta(0),
    )
