"""Outcome domain model.

An Outcome is an "achieved state/result" (``docs/02-CONCEPTUAL-MODEL.md``,
the Planning Layer) — the concrete thing a plan commits to producing.
Outcomes are what milestones measure (TASK-026's decision: a milestone
carries no lifecycle of its own because its achievement is expressed
through its outcomes) and what tasks serve (Outcome N:M Tasks,
docs/03).

Relationships (docs/03):

- Plan 1:N Outcomes — every outcome belongs to exactly one plan;
- Milestone 1:N Outcomes — optionally, an outcome is the measurable
  content of one milestone. A plan-level outcome without a milestone
  is legitimate: milestones are checkpoints, not the only way to
  state what "done" means;
- Outcome may exist without Tasks (docs/03) — the N:M link is
  established by the task model, never required here.

Rules:

- IDs are UUIDs; ``plan_id`` references the owning plan.
- ``title`` is non-empty, stripped, ≤ 200 characters; ``description``
  is optional free text ≤ 5000 characters.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
- An outcome carries no lifecycle of its own: like a milestone, its
  achievement is measured (the progress epic's concern), not flagged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from backcasting.domain.milestone import Milestone
from backcasting.domain.plan import Plan
from backcasting.domain.timezone import UTC

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000


class OutcomeError(ValueError):
    """Raised when an outcome invariant is violated."""


@dataclass(frozen=True)
class Outcome:
    """An achieved state/result a plan commits to producing."""

    outcome_id: uuid.UUID
    plan_id: uuid.UUID
    title: str
    description: str = ""
    milestone_id: uuid.UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.outcome_id, uuid.UUID):
            raise OutcomeError("outcome_id must be a UUID")
        if not isinstance(self.plan_id, uuid.UUID):
            raise OutcomeError("plan_id must be a UUID")
        title = self.title
        if not isinstance(title, str) or not title.strip():
            raise OutcomeError("title must be a non-empty string")
        if len(title.strip()) > MAX_TITLE_LENGTH:
            raise OutcomeError(f"title must be at most {MAX_TITLE_LENGTH} characters")
        object.__setattr__(self, "title", title.strip())
        description = self.description
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise OutcomeError("description must be a string")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise OutcomeError(
                f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        object.__setattr__(self, "description", description)
        if self.milestone_id is not None and not isinstance(
            self.milestone_id, uuid.UUID
        ):
            raise OutcomeError("milestone_id must be a UUID or None")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise OutcomeError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise OutcomeError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise OutcomeError("updated_at must not precede created_at")


def define_outcome(
    plan: Plan,
    title: str,
    *,
    description: str = "",
    milestone: Milestone | None = None,
    outcome_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Outcome:
    """Define an outcome on ``plan``.

    ``milestone``, when given, binds the outcome to that checkpoint
    (Milestone 1:N Outcomes); an outcome without one is a plan-level
    statement of a result.
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    if milestone is not None and not isinstance(milestone, Milestone):
        raise TypeError("milestone must be a Milestone or None")
    now = created_at if created_at is not None else datetime.now(UTC)
    return Outcome(
        outcome_id=outcome_id if outcome_id is not None else uuid.uuid4(),
        plan_id=plan.plan_id,
        title=title,
        description=description,
        milestone_id=milestone.milestone_id if milestone is not None else None,
        created_at=now,
        updated_at=now,
    )


def revise_outcome(
    outcome: Outcome,
    *,
    updated_at: datetime,
    title: str | None = None,
    description: str | None = None,
) -> Outcome:
    """Return a revised copy of ``outcome`` with ``updated_at`` advanced.

    The Outcome's identity, plan, milestone binding, and ``created_at``
    are carried over unchanged; only the descriptive fields move. A
    revision never re-binds the outcome to another milestone — that is
    a different outcome, not a revision.
    """
    if not isinstance(outcome, Outcome):
        raise TypeError("outcome must be an Outcome")
    return replace(
        outcome,
        title=title if title is not None else outcome.title,
        description=(
            description if description is not None else outcome.description
        ),
        updated_at=updated_at,
    )
