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
- Task N:M Resources — a task may require any number of shared
  resources, linked through ``resource_ids`` (TASK-052); resources
  are user-level context, not plan-scoped, so any task may link any
  resource;
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
- ``outcome_ids`` are unique UUIDs of the outcomes the task serves;
  ``resource_ids`` are unique UUIDs of the resources it requires.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from backcasting.domain.outcome import Outcome
from backcasting.domain.plan import Plan, PlanStatus, is_terminal
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
    resource_ids: frozenset[uuid.UUID] = frozenset()
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
        resource_ids = frozenset(self.resource_ids)
        for resource_id in resource_ids:
            if not isinstance(resource_id, uuid.UUID):
                raise TaskError("resource_ids must contain UUIDs")
        object.__setattr__(self, "resource_ids", resource_ids)
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

    The Task's identity, plan, outcome and resource links, and
    ``created_at`` are carried over unchanged; only the editable
    fields move. Passing ``None`` for a field keeps it — clearing a
    duration or deadline belongs to explicit resets, not accidental
    omissions.
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


@dataclass(frozen=True)
class TaskProposal:
    """A raw task proposal as an AI adapter emits it.

    The decomposition contract for pipeline step 12, "Generate tasks"
    (docs/04): the LLM decomposes outcomes into proposed tasks
    ("outcome decomposition, task generation", docs/09) and the domain
    validates (:func:`accept_proposed_tasks`). Outcome bindings are
    referenced by the outcome's title — the proposal carries no ids,
    because ids are the domain's to assign.
    """

    title: str
    description: str = ""
    duration: timedelta | None = None
    deadline: datetime | None = None
    outcome_titles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        title = self.title
        if not isinstance(title, str) or not title.strip():
            raise TaskError("proposal title must be a non-empty string")
        if len(title.strip()) > MAX_TITLE_LENGTH:
            raise TaskError(
                f"proposal title must be at most {MAX_TITLE_LENGTH} characters"
            )
        object.__setattr__(self, "title", title.strip())
        description = self.description
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise TaskError("proposal description must be a string")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise TaskError(
                f"proposal description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        object.__setattr__(self, "description", description)
        if self.duration is not None:
            if (
                not isinstance(self.duration, timedelta)
                or self.duration <= timedelta(0)
            ):
                raise TaskError("proposal duration must be a strictly positive timedelta")
        if self.deadline is not None:
            require_utc("proposal deadline", self.deadline, error=TaskError)
        outcome_titles = self.outcome_titles
        if not isinstance(outcome_titles, tuple):
            raise TaskError("proposal outcome_titles must be a tuple of str")
        cleaned: list[str] = []
        for outcome_title in outcome_titles:
            if not isinstance(outcome_title, str) or not outcome_title.strip():
                raise TaskError("proposal outcome_titles must be non-empty strings")
            cleaned.append(outcome_title.strip())
        object.__setattr__(self, "outcome_titles", tuple(cleaned))


def accept_proposed_tasks(
    plan: Plan,
    outcomes: tuple[Outcome, ...],
    proposals: tuple[TaskProposal, ...],
    *,
    at: datetime | None = None,
) -> tuple[Task, ...]:
    """Accept AI-proposed tasks for a plan (pipeline step 12).

    Deterministic rules enforced here (ADR-002: "The LLM proposes and
    reasons; the Domain validates and enforces"):

    - The plan must not be terminal — a SUPERSEDED, ARCHIVED, or
      INVALID plan cannot gain tasks; generation targets a plan that
      is still being shaped.
    - Every supplied outcome must belong to the plan, and outcome
      titles must be unique among them — a proposal's title reference
      must resolve to exactly one outcome.
    - At least one proposal must be supplied — an empty generation is
      a failed step, not a valid outcome (mirroring milestones).
    - Task titles must be unique within the batch.
    - Every referenced outcome title must resolve; an unresolved
      reference is a contract violation, not a silently dropped link.

    Returns the created tasks in proposal order, sharing ``at`` as
    their creation time, each serving its resolved outcomes.
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    if not isinstance(outcomes, tuple):
        raise TaskError("outcomes must be a tuple of Outcome")
    for outcome in outcomes:
        if not isinstance(outcome, Outcome):
            raise TaskError("outcomes must be Outcome instances")
        if outcome.plan_id != plan.plan_id:
            raise TaskError("outcome does not belong to this plan")
    if not isinstance(proposals, tuple):
        raise TaskError("proposals must be a tuple of TaskProposal")
    if is_terminal(plan.status):
        raise TaskError(
            f"cannot accept tasks for a plan with status {plan.status.value}"
        )
    by_title: dict[str, Outcome] = {}
    for outcome in outcomes:
        if outcome.title in by_title:
            raise TaskError(f"duplicate outcome title: {outcome.title}")
        by_title[outcome.title] = outcome
    if not proposals:
        raise TaskError("at least one task proposal is required")
    now = at if at is not None else datetime.now(UTC)
    titles: set[str] = set()
    for proposal in proposals:
        if not isinstance(proposal, TaskProposal):
            raise TaskError("proposals must be TaskProposal instances")
        if proposal.title in titles:
            raise TaskError(f"duplicate task title: {proposal.title}")
        titles.add(proposal.title)
        for outcome_title in proposal.outcome_titles:
            if outcome_title not in by_title:
                raise TaskError(
                    f"proposal references unknown outcome: {outcome_title}"
                )
    tasks: list[Task] = []
    for proposal in proposals:
        task = create_task(
            plan,
            proposal.title,
            description=proposal.description,
            duration=proposal.duration,
            deadline=proposal.deadline,
            created_at=now,
        )
        resolved = tuple(
            by_title[outcome_title] for outcome_title in proposal.outcome_titles
        )
        if resolved:
            task = serve_outcomes(task, resolved, updated_at=now)
        tasks.append(task)
    return tuple(tasks)
