"""Task domain model.

A Task is an "actionable unit of work" (``docs/02-CONCEPTUAL-MODEL.md``,
the Execution Layer) — the schedulable grain of a plan. Scheduling
"places schedulable tasks into feasible time slots" (docs/06): a task
becomes schedulable once it carries a duration to place (estimation
enriches this in its own task; the scheduling epic consumes it).

Relationships (docs/03):

- Plan 1:N Tasks — every task belongs to exactly one plan;
- Outcome N:M Tasks — a task may serve multiple outcomes, linked by
  :func:`serve_outcomes`, which keeps the N:M inside one plan (a task
  cannot serve another plan's outcome);
- Task 1:N Schedules and Task 1:N Executions — placements in time and
  records of doing, both later epics' concerns, never embedded here;
- Task N:M Resources — the resources task (TASK-052);
- "Calendar Event is not necessarily a Task" (docs/03) — the two
  concepts stay separate: a schedule *places* a task into calendar
  time; it does not turn it into an event.

Rules:

- IDs are UUIDs; ``plan_id`` references the owning plan.
- ``title`` is non-empty, stripped, ≤ 200 characters; ``description``
  is optional free text ≤ 5000 characters.
- ``duration`` is the estimated time to execute: ``None`` until
  estimated, strictly positive once set.
- ``deadline`` is an optional timezone-aware UTC instant strictly
  after ``created_at`` — the deadline layer of the scheduling
  hierarchy (docs/05).
- ``outcome_ids`` are unique UUIDs of the outcomes the task serves.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from backcasting.domain.outcome import Outcome
from backcasting.domain.plan import Plan
from backcasting.domain.timezone import UTC, require_utc

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000


class TaskError(ValueError):
    """Raised when a task invariant is violated."""


@dataclass(frozen=True)
class Task:
    """An actionable unit of work in a plan."""

    task_id: uuid.UUID
    plan_id: uuid.UUID
    title: str
    description: str = ""
    duration: timedelta | None = None
    deadline: datetime | None = None
    outcome_ids: frozenset[uuid.UUID] = frozenset()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, uuid.UUID):
            raise TaskError("task_id must be a UUID")
        if not isinstance(self.plan_id, uuid.UUID):
            raise TaskError("plan_id must be a UUID")
        title = self.title
        if not isinstance(title, str) or not title.strip():
            raise TaskError("title must be a non-empty string")
        if len(title.strip()) > MAX_TITLE_LENGTH:
            raise TaskError(f"title must be at most {MAX_TITLE_LENGTH} characters")
        object.__setattr__(self, "title", title.strip())
        description = self.description
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise TaskError("description must be a string")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise TaskError(
                f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        object.__setattr__(self, "description", description)
        if self.duration is not None:
            if not isinstance(self.duration, timedelta) or self.duration <= timedelta(0):
                raise TaskError("duration must be a strictly positive timedelta")
        if self.deadline is not None:
            require_utc("deadline", self.deadline, error=TaskError)
            if self.deadline <= self.created_at:
                raise TaskError("deadline must be after created_at")
        outcome_ids = frozenset(self.outcome_ids)
        for outcome_id in outcome_ids:
            if not isinstance(outcome_id, uuid.UUID):
                raise TaskError("outcome_ids must contain UUIDs")
        object.__setattr__(self, "outcome_ids", outcome_ids)
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise TaskError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise TaskError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise TaskError("updated_at must not precede created_at")


def create_task(
    plan: Plan,
    title: str,
    *,
    description: str = "",
    duration: timedelta | None = None,
    deadline: datetime | None = None,
    task_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Task:
    """Create a Task on ``plan``.

    ``duration`` may be omitted — the task simply is not schedulable
    until an estimate lands (see :func:`is_schedulable`).
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    now = created_at if created_at is not None else datetime.now(UTC)
    return Task(
        task_id=task_id if task_id is not None else uuid.uuid4(),
        plan_id=plan.plan_id,
        title=title,
        description=description,
        duration=duration,
        deadline=deadline,
        created_at=now,
        updated_at=now,
    )


def revise_task(
    task: Task,
    *,
    updated_at: datetime,
    title: str | None = None,
    description: str | None = None,
    duration: timedelta | None = None,
    deadline: datetime | None = None,
) -> Task:
    """Return a revised copy of ``task`` with ``updated_at`` advanced.

    The Task's identity, plan, outcome links, and ``created_at`` are
    carried over unchanged; only the editable fields move. Passing
    ``None`` for a field keeps it — clearing a duration or deadline
    belongs to explicit resets, not accidental omissions.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    return replace(
        task,
        title=title if title is not None else task.title,
        description=(
            description if description is not None else task.description
        ),
        duration=duration if duration is not None else task.duration,
        deadline=deadline if deadline is not None else task.deadline,
        updated_at=updated_at,
    )


def serve_outcomes(
    task: Task,
    outcomes: tuple[Outcome, ...],
    *,
    updated_at: datetime,
) -> Task:
    """Return ``task`` extended to serve ``outcomes`` (Outcome N:M Tasks).

    Every outcome must belong to the task's plan — a task cannot serve
    another plan's outcome. The link set is a union, so re-serving an
    already-linked outcome is idempotent.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    if not isinstance(outcomes, tuple):
        raise TaskError("outcomes must be a tuple of Outcome")
    for outcome in outcomes:
        if not isinstance(outcome, Outcome):
            raise TaskError("outcomes must be Outcome instances")
        if outcome.plan_id != task.plan_id:
            raise TaskError("outcome does not belong to this task's plan")
    linked = task.outcome_ids | {outcome.outcome_id for outcome in outcomes}
    return replace(task, outcome_ids=frozenset(linked), updated_at=updated_at)


def is_schedulable(task: Task) -> bool:
    """Whether the task is ready for slot placement: it has a duration."""
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    return task.duration is not None
