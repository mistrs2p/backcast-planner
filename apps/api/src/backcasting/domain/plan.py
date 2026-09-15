"""Plan domain model.

A Plan is the executable shape of a goal's chosen path — "what must
happen and the workload required" (docs/06-PLANNING-SCHEDULING.md).
It belongs to a Goal ("Goal 1:N Plans", docs/03) and is the root the
planning epic hangs its structure from: milestones, outcomes, and
tasks (each 1:N off the Plan, docs/03) arrive in their own tasks.

Plans are *adaptive* by product principle ("Plans are adaptive; goals
require explicit revision", docs/00): revising a plan's workload or
title is routine and never touches the goal, while the goal's own
changes go through its explicit revision path.

Lifecycle (docs/03): ``DRAFT/CANDIDATE → ACTIVE →
SUPERSEDED/ARCHIVED/INVALID``. A plan is authored as DRAFT, becomes a
CANDIDATE once complete enough to evaluate, and ACTIVE once chosen.
An ACTIVE plan ends SUPERSEDED (replaced by a newer plan), ARCHIVED,
or INVALID (its assumptions no longer hold). The pre-active states
may also be ARCHIVED (an abandoned draft, a rejected candidate); the
terminal states have no outgoing transitions.

Key rules:

- IDs are UUIDs; ``goal_id`` references the owning goal.
- ``run_id`` is optional provenance — the backcasting run whose
  result the plan was born from. A plan may also be authored
  directly, so it is not required.
- ``title`` is optional free text ≤ 200 characters; ``workload`` is
  the total required workload, a non-negative timedelta.
- A goal has *max one* ACTIVE plan (docs/03) — :func:`active_plan`
  enforces the invariant when reading it back.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum

from backcasting.domain.goal import Goal
from backcasting.domain.timezone import UTC

MAX_TITLE_LENGTH = 200


class PlanError(ValueError):
    """Raised when a plan invariant is violated."""


class PlanStatus(str, Enum):
    """Lifecycle states of a Plan (docs/03-DOMAIN-MODEL.md)."""

    DRAFT = "draft"
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    INVALID = "invalid"


#: Allowed status transitions, per the spec lifecycle
#: ``DRAFT/CANDIDATE → ACTIVE → SUPERSEDED/ARCHIVED/INVALID``
#: (docs/03-DOMAIN-MODEL.md). A plan is authored as DRAFT and proposed
#: as a CANDIDATE; either pre-active state may be ARCHIVED (abandoned
#: or rejected). Only an ACTIVE plan can be SUPERSEDED or INVALID —
#: replacement and invalidation are things that happen to plans that
#: were once in force. Terminal states have no outgoing transitions.
PLAN_TRANSITIONS: dict[PlanStatus, frozenset[PlanStatus]] = {
    PlanStatus.DRAFT: frozenset({PlanStatus.CANDIDATE, PlanStatus.ARCHIVED}),
    PlanStatus.CANDIDATE: frozenset({PlanStatus.ACTIVE, PlanStatus.ARCHIVED}),
    PlanStatus.ACTIVE: frozenset(
        {
            PlanStatus.SUPERSEDED,
            PlanStatus.ARCHIVED,
            PlanStatus.INVALID,
        }
    ),
    PlanStatus.SUPERSEDED: frozenset(),
    PlanStatus.ARCHIVED: frozenset(),
    PlanStatus.INVALID: frozenset(),
}

#: Statuses with no outgoing transitions.
TERMINAL_PLAN_STATUSES = frozenset(
    {
        PlanStatus.SUPERSEDED,
        PlanStatus.ARCHIVED,
        PlanStatus.INVALID,
    }
)


class InvalidPlanTransition(PlanError):
    """Raised when a Plan status transition violates the lifecycle rules."""

    def __init__(self, from_status: PlanStatus, to_status: PlanStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"illegal plan transition: {from_status.value} -> {to_status.value}"
        )


@dataclass(frozen=True)
class Plan:
    """The executable plan of a goal: what must happen, and its workload."""

    plan_id: uuid.UUID
    goal_id: uuid.UUID
    workload: timedelta
    status: PlanStatus = PlanStatus.DRAFT
    title: str = ""
    run_id: uuid.UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.plan_id, uuid.UUID):
            raise PlanError("plan_id must be a UUID")
        if not isinstance(self.goal_id, uuid.UUID):
            raise PlanError("goal_id must be a UUID")
        if not isinstance(self.workload, timedelta) or self.workload < timedelta(0):
            raise PlanError("workload must be a non-negative timedelta")
        if not isinstance(self.status, PlanStatus):
            raise PlanError("status must be a PlanStatus")
        title = self.title
        if title is None:
            title = ""
        if not isinstance(title, str):
            raise PlanError("title must be a string")
        if len(title) > MAX_TITLE_LENGTH:
            raise PlanError(f"title must be at most {MAX_TITLE_LENGTH} characters")
        object.__setattr__(self, "title", title)
        if self.run_id is not None and not isinstance(self.run_id, uuid.UUID):
            raise PlanError("run_id must be a UUID or None")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise PlanError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise PlanError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise PlanError("updated_at must not precede created_at")


def create_plan(
    goal: Goal,
    workload: timedelta,
    *,
    title: str = "",
    run_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Plan:
    """Create a Plan in DRAFT for ``goal``.

    ``run_id`` may carry the provenance of the backcasting run the plan
    was born from; a directly authored plan omits it.
    """
    if not isinstance(goal, Goal):
        raise TypeError("goal must be a Goal")
    now = created_at if created_at is not None else datetime.now(UTC)
    return Plan(
        plan_id=plan_id if plan_id is not None else uuid.uuid4(),
        goal_id=goal.goal_id,
        workload=workload,
        status=PlanStatus.DRAFT,
        title=title,
        run_id=run_id,
        created_at=now,
        updated_at=now,
    )


def revise_plan(
    plan: Plan,
    *,
    updated_at: datetime,
    title: str | None = None,
    workload: timedelta | None = None,
) -> Plan:
    """Return a revised copy of ``plan`` with ``updated_at`` advanced.

    The Plan's identity, ownership, status, provenance, and
    ``created_at`` are carried over unchanged; only the editable
    fields move. Status changes are not allowed here — they belong to
    :func:`transition_plan`.
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    return replace(
        plan,
        title=title if title is not None else plan.title,
        workload=workload if workload is not None else plan.workload,
        updated_at=updated_at,
    )


def can_transition(plan: Plan, to_status: PlanStatus) -> bool:
    """Whether ``plan`` may move to ``to_status`` under the lifecycle rules."""
    if not isinstance(to_status, PlanStatus):
        raise PlanError("to_status must be a PlanStatus")
    return to_status in PLAN_TRANSITIONS[plan.status]


def is_terminal(status: PlanStatus) -> bool:
    """Whether ``status`` is a terminal lifecycle state."""
    if not isinstance(status, PlanStatus):
        raise PlanError("status must be a PlanStatus")
    return status in TERMINAL_PLAN_STATUSES


def transition_plan(
    plan: Plan,
    to_status: PlanStatus,
    *,
    at: datetime | None = None,
) -> Plan:
    """Return ``plan`` moved to ``to_status``, advancing ``updated_at``.

    Raises :class:`InvalidPlanTransition` for any transition not
    present in :data:`PLAN_TRANSITIONS` (including same-status
    transitions and any move out of a terminal state). Identity,
    ownership, provenance, and ``created_at`` are carried over
    unchanged.
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    if not isinstance(to_status, PlanStatus):
        raise PlanError("to_status must be a PlanStatus")
    if to_status not in PLAN_TRANSITIONS[plan.status]:
        raise InvalidPlanTransition(plan.status, to_status)
    moved_at = at if at is not None else datetime.now(UTC)
    return replace(plan, status=to_status, updated_at=moved_at)


def active_plan(plans: tuple[Plan, ...], goal_id: uuid.UUID) -> Plan | None:
    """The single ACTIVE plan of ``goal_id``, or ``None`` if there is none.

    "Goal max 1 Active Plan" (docs/03): more than one ACTIVE plan for
    a goal is a corrupted state, not a query result — it raises rather
    than picking one.
    """
    if not isinstance(plans, tuple):
        raise PlanError("plans must be a tuple of Plan")
    if not isinstance(goal_id, uuid.UUID):
        raise PlanError("goal_id must be a UUID")
    active = tuple(
        plan
        for plan in plans
        if isinstance(plan, Plan) and plan.goal_id == goal_id
        and plan.status is PlanStatus.ACTIVE
    )
    if len(active) > 1:
        raise PlanError(
            f"goal {goal_id} has {len(active)} active plans; at most one is allowed"
        )
    return active[0] if active else None
