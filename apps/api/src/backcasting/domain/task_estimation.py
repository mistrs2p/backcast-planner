"""Task estimation domain model.

Pipeline step 6 is "Estimate workload" (docs/04). Goal-level workload
arrives at :func:`execute_backcasting` as an input; this module is the
task-level half: how a Task receives its ``duration`` — "the estimated
time to execute" (TASK-050) — and how a plan's tasks sum into the
workload the feasibility rule consumes.

Per ADR-002 ("The LLM proposes and reasons; the Domain validates and
enforces") an estimate is a *record with provenance*, not just a
number: a :class:`TaskEstimation` carries the duration, who produced
it (:class:`EstimationSource` — a human or the LLM), and why. Records
are append-only; re-estimation adds a record, and
:func:`latest_estimation` finds the current one. Applying an estimate
to a task (:func:`apply_estimation`) is the only sanctioned way a
duration lands, and it is validated: the estimate must belong to the
task it claims.

:func:`estimate_workload` is the step-6 aggregation — the sum of a
plan's task durations. It refuses to sum silently over unestimated
tasks: an estimate that is missing is a fact to surface, not a zero
to hide ("the LLM proposes and reasons" — never guesses here).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from backcasting.domain.task import Task, revise_task
from backcasting.domain.timezone import UTC, require_utc

MAX_RATIONALE_LENGTH = 500


class TaskEstimationError(ValueError):
    """Raised when a task-estimation invariant is violated."""


class EstimationSource(str, Enum):
    """Who produced an estimate."""

    MANUAL = "manual"
    AI = "ai"


@dataclass(frozen=True)
class TaskEstimation:
    """One duration estimate for one task, with provenance."""

    estimation_id: uuid.UUID
    task_id: uuid.UUID
    duration: timedelta
    source: EstimationSource = EstimationSource.MANUAL
    rationale: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.estimation_id, uuid.UUID):
            raise TaskEstimationError("estimation_id must be a UUID")
        if not isinstance(self.task_id, uuid.UUID):
            raise TaskEstimationError("task_id must be a UUID")
        if not isinstance(self.duration, timedelta) or self.duration <= timedelta(0):
            raise TaskEstimationError("duration must be a strictly positive timedelta")
        if not isinstance(self.source, EstimationSource):
            raise TaskEstimationError("source must be an EstimationSource")
        rationale = self.rationale
        if rationale is None:
            rationale = ""
        if not isinstance(rationale, str):
            raise TaskEstimationError("rationale must be a string")
        if len(rationale.strip()) > MAX_RATIONALE_LENGTH:
            raise TaskEstimationError(
                f"rationale must be at most {MAX_RATIONALE_LENGTH} characters"
            )
        object.__setattr__(self, "rationale", rationale.strip())
        require_utc("created_at", self.created_at, error=TaskEstimationError)


def record_estimation(
    task: Task,
    duration: timedelta,
    *,
    source: EstimationSource = EstimationSource.MANUAL,
    rationale: str = "",
    estimation_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> TaskEstimation:
    """Record a duration estimate for ``task``.

    The record is append-only history — it does not modify the task;
    :func:`apply_estimation` moves the duration onto it.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    return TaskEstimation(
        estimation_id=estimation_id if estimation_id is not None else uuid.uuid4(),
        task_id=task.task_id,
        duration=duration,
        source=source,
        rationale=rationale,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def apply_estimation(
    task: Task,
    estimation: TaskEstimation,
    *,
    updated_at: datetime,
) -> Task:
    """Return ``task`` carrying ``estimation``'s duration.

    The estimate must belong to the task it is applied to — an
    estimate for another task is a fact about that task, not this
    one. The task's identity, links, and ``created_at`` are carried
    over unchanged; this makes the task schedulable (it now has a
    duration).
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    if not isinstance(estimation, TaskEstimation):
        raise TypeError("estimation must be a TaskEstimation")
    if estimation.task_id != task.task_id:
        raise TaskEstimationError("estimation does not belong to this task")
    return revise_task(task, duration=estimation.duration, updated_at=updated_at)


def latest_estimation(
    estimations: tuple[TaskEstimation, ...],
    task_id: uuid.UUID,
) -> TaskEstimation | None:
    """The most recent estimate for ``task_id``, or ``None``.

    Ties on ``created_at`` break toward the later position in the
    tuple, so appending a re-estimate wins — order-independent for
    genuinely distinct timestamps.
    """
    if not isinstance(estimations, tuple):
        raise TaskEstimationError("estimations must be a tuple of TaskEstimation")
    for estimation in estimations:
        if not isinstance(estimation, TaskEstimation):
            raise TaskEstimationError("estimations must be TaskEstimation instances")
    if not isinstance(task_id, uuid.UUID):
        raise TaskEstimationError("task_id must be a UUID")
    best: TaskEstimation | None = None
    for estimation in estimations:
        if estimation.task_id != task_id:
            continue
        if best is None or estimation.created_at >= best.created_at:
            best = estimation
    return best


def estimate_workload(tasks: tuple[Task, ...]) -> timedelta:
    """Sum the durations of ``tasks`` (pipeline step 6, task level).

    Every task must carry a duration — an unestimated task makes the
    workload unknown, and summing over it would silently understate
    the plan. The empty sum is zero: a plan with no tasks needs no
    work.
    """
    if not isinstance(tasks, tuple):
        raise TaskEstimationError("tasks must be a tuple of Task")
    total = timedelta(0)
    for task in tasks:
        if not isinstance(task, Task):
            raise TaskEstimationError("tasks must be Task instances")
        if task.duration is None:
            raise TaskEstimationError(
                f"task {task.task_id} ({task.title!r}) has no estimate"
            )
        total += task.duration
    return total
