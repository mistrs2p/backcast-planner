"""Goal domain model.

The Goal is the user's intention — the root of the planning aggregate
(`docs/02-CONCEPTUAL-MODEL.md` "Intent Layer"). A user owns many goals
(`docs/03-DOMAIN-MODEL.md` "User 1:N Goals"); each goal relates 1:1 to a
Desired Future State in the MVP and anchors backcasting runs and plans.

This module defines the entity, its ownership, the lifecycle states, and
the :data:`GOAL_TRANSITIONS` rules governing movement between them.

Rules:

- IDs are UUIDs; ``user_id`` references the owning User.
- ``title`` is a non-empty, stripped string (≤ 200 characters).
- ``description`` is optional free text (≤ 2000 characters).
- Lifecycle states per ``docs/03-DOMAIN-MODEL.md``:
  DRAFT → ACTIVE → PAUSED → COMPLETED/CANCELLED/ARCHIVED.
  A new goal starts in DRAFT.
- ``created_at``/``updated_at`` must be timezone-aware and UTC; a Goal is
  immutable — "changes" produce a new instance via :func:`replace`, which
  advances ``updated_at`` (see ``AGENTS.md`` §7 on time handling).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000


class GoalError(ValueError):
    """Raised when a Goal invariant is violated."""


class GoalStatus(str, Enum):
    """Lifecycle states of a Goal (docs/03-DOMAIN-MODEL.md)."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


#: Allowed status transitions, per the spec lifecycle
#: ``DRAFT → ACTIVE → PAUSED → COMPLETED/CANCELLED/ARCHIVED``
#: (docs/03-DOMAIN-MODEL.md): a goal becomes active, may be paused, and
#: ends in one of the three terminal states. The terminal states are also
#: reachable directly from ACTIVE, and PAUSED may resume to ACTIVE — a
#: pause that could never resume would be indistinguishable from
#: cancellation. Terminal states have no outgoing transitions.
GOAL_TRANSITIONS: dict[GoalStatus, frozenset[GoalStatus]] = {
    GoalStatus.DRAFT: frozenset({GoalStatus.ACTIVE}),
    GoalStatus.ACTIVE: frozenset(
        {
            GoalStatus.PAUSED,
            GoalStatus.COMPLETED,
            GoalStatus.CANCELLED,
            GoalStatus.ARCHIVED,
        }
    ),
    GoalStatus.PAUSED: frozenset(
        {
            GoalStatus.ACTIVE,
            GoalStatus.COMPLETED,
            GoalStatus.CANCELLED,
            GoalStatus.ARCHIVED,
        }
    ),
    GoalStatus.COMPLETED: frozenset(),
    GoalStatus.CANCELLED: frozenset(),
    GoalStatus.ARCHIVED: frozenset(),
}

#: Statuses with no outgoing transitions.
TERMINAL_GOAL_STATUSES = frozenset(
    {
        GoalStatus.COMPLETED,
        GoalStatus.CANCELLED,
        GoalStatus.ARCHIVED,
    }
)


class InvalidGoalTransition(GoalError):
    """Raised when a Goal status transition violates the lifecycle rules."""

    def __init__(self, from_status: GoalStatus, to_status: GoalStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"illegal goal transition: {from_status.value} -> {to_status.value}"
        )


@dataclass(frozen=True)
class Goal:
    """A user's intention, root of the planning aggregate."""

    goal_id: uuid.UUID
    user_id: uuid.UUID
    title: str
    description: str = ""
    status: GoalStatus = GoalStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.goal_id, uuid.UUID):
            raise GoalError("goal_id must be a UUID")
        if not isinstance(self.user_id, uuid.UUID):
            raise GoalError("user_id must be a UUID")
        title = self.title
        if not isinstance(title, str) or not title.strip():
            raise GoalError("title must be a non-empty string")
        if len(title.strip()) > MAX_TITLE_LENGTH:
            raise GoalError(f"title must be at most {MAX_TITLE_LENGTH} characters")
        object.__setattr__(self, "title", title.strip())
        description = self.description
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise GoalError("description must be a string")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise GoalError(
                f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        object.__setattr__(self, "description", description)
        if not isinstance(self.status, GoalStatus):
            raise GoalError("status must be a GoalStatus")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise GoalError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise GoalError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise GoalError("updated_at must not precede created_at")


def create_goal(
    user_id: uuid.UUID,
    title: str,
    *,
    description: str = "",
    goal_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Goal:
    """Create a Goal in DRAFT, generating identity and timestamps.

    ``goal_id`` and ``created_at`` may be injected for deterministic tests;
    ``created_at`` must still be timezone-aware UTC.
    """
    now = created_at if created_at is not None else datetime.now(timezone.utc)
    return Goal(
        goal_id=goal_id if goal_id is not None else uuid.uuid4(),
        user_id=user_id,
        title=title,
        description=description,
        status=GoalStatus.DRAFT,
        created_at=now,
        updated_at=now,
    )


def revise_goal(
    goal: Goal,
    *,
    updated_at: datetime,
    title: str | None = None,
    description: str | None = None,
) -> Goal:
    """Return a revised copy of ``goal`` with ``updated_at`` advanced.

    The Goal's identity, ownership, status, and ``created_at`` are carried
    over unchanged; only the editable fields move. Status changes are not
    allowed here — they belong to :func:`transition_goal`.
    """
    return replace(
        goal,
        title=title if title is not None else goal.title,
        description=(
            description if description is not None else goal.description
        ),
        updated_at=updated_at,
    )


def can_transition(goal: Goal, to_status: GoalStatus) -> bool:
    """Whether ``goal`` may move to ``to_status`` under the lifecycle rules."""
    if not isinstance(to_status, GoalStatus):
        raise GoalError("to_status must be a GoalStatus")
    return to_status in GOAL_TRANSITIONS[goal.status]


def is_terminal(status: GoalStatus) -> bool:
    """Whether ``status`` is a terminal lifecycle state."""
    if not isinstance(status, GoalStatus):
        raise GoalError("status must be a GoalStatus")
    return status in TERMINAL_GOAL_STATUSES


def transition_goal(
    goal: Goal,
    to_status: GoalStatus,
    *,
    at: datetime | None = None,
) -> Goal:
    """Return ``goal`` moved to ``to_status``, advancing ``updated_at``.

    Raises :class:`InvalidGoalTransition` for any transition not present in
    :data:`GOAL_TRANSITIONS` (including same-status transitions and any
    move out of a terminal state). Identity, ownership, and ``created_at``
    are carried over unchanged.
    """
    if not isinstance(to_status, GoalStatus):
        raise GoalError("to_status must be a GoalStatus")
    if to_status not in GOAL_TRANSITIONS[goal.status]:
        raise InvalidGoalTransition(goal.status, to_status)
    moved_at = at if at is not None else datetime.now(timezone.utc)
    return replace(goal, status=to_status, updated_at=moved_at)
