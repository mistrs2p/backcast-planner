"""Desired Future State domain model.

The Desired Future is the destination state — where the user wants to end up
(`docs/02-CONCEPTUAL-MODEL.md` "Intent Layer"). In the MVP a Goal relates
1:1 to its Future State (`docs/03-DOMAIN-MODEL.md`), and the backcasting
pipeline reasons backward from it (``docs/04-BACKCASTING-MODEL.md`` step 3).

Per ``docs/08-REPLANNING-MODEL.md``, replanning *preserves* the Goal and
Future State; only an explicit Goal Revision changes the destination. This
module therefore exposes :func:`revise_future_state` for those explicit
changes and keeps instances otherwise immutable.

Rules:

- IDs are UUIDs; ``goal_id`` references the Goal (1:1 in the MVP — the
  uniqueness itself is a persistence concern, enforced by the repository
  layer, not by this value).
- ``description`` is the destination state: non-empty, stripped,
  ≤ 5000 characters.
- ``target_date`` is the time anchor backcasting plans backward from:
  timezone-aware UTC, strictly after ``created_at`` (a destination is by
  definition in the future relative to when it was defined).
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

MAX_DESCRIPTION_LENGTH = 5000


class FutureStateError(ValueError):
    """Raised when a FutureState invariant is violated."""


@dataclass(frozen=True)
class FutureState:
    """The destination state a Goal is backcast from."""

    state_id: uuid.UUID
    goal_id: uuid.UUID
    description: str
    target_date: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.state_id, uuid.UUID):
            raise FutureStateError("state_id must be a UUID")
        if not isinstance(self.goal_id, uuid.UUID):
            raise FutureStateError("goal_id must be a UUID")
        description = self.description
        if not isinstance(description, str) or not description.strip():
            raise FutureStateError("description must be a non-empty string")
        if len(description.strip()) > MAX_DESCRIPTION_LENGTH:
            raise FutureStateError(
                f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        object.__setattr__(self, "description", description.strip())
        for stamp_name in ("target_date", "created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise FutureStateError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise FutureStateError(f"{stamp_name} must be in UTC")
        if self.target_date <= self.created_at:
            raise FutureStateError("target_date must be after created_at")
        if self.updated_at < self.created_at:
            raise FutureStateError("updated_at must not precede created_at")


def define_future_state(
    goal_id: uuid.UUID,
    description: str,
    target_date: datetime,
    *,
    state_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> FutureState:
    """Define the destination for a Goal, generating identity when omitted.

    ``state_id`` and ``created_at`` may be injected for deterministic tests;
    both must still satisfy the UTC-awareness invariants.
    """
    now = created_at if created_at is not None else datetime.now(timezone.utc)
    return FutureState(
        state_id=state_id if state_id is not None else uuid.uuid4(),
        goal_id=goal_id,
        description=description,
        target_date=target_date,
        created_at=now,
        updated_at=now,
    )


def revise_future_state(
    state: FutureState,
    *,
    updated_at: datetime,
    description: str | None = None,
    target_date: datetime | None = None,
) -> FutureState:
    """Return an explicitly revised copy of the destination.

    Identity, goal ownership, and ``created_at`` carry over unchanged. This
    is the only sanctioned way to change the destination (Goal Revision,
    ``docs/08-REPLANNING-MODEL.md``) — replanning must not call it.
    """
    return replace(
        state,
        description=(
            description if description is not None else state.description
        ),
        target_date=(
            target_date if target_date is not None else state.target_date
        ),
        updated_at=updated_at,
    )
