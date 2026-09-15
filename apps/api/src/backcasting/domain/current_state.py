"""Current State domain model.

The Current State is a snapshot of present reality for a Goal
(`docs/02-CONCEPTUAL-MODEL.md` "Planning Layer"). It is an input to the
backcasting pipeline (``docs/04-BACKCASTING-MODEL.md`` step 2, "Determine
Current State") and is re-captured during replanning ("Re-run the same core
engine with a new Current State and updated context"), so a goal accumulates
snapshots over time rather than mutating one.

Rules:

- IDs are UUIDs; ``goal_id`` references the Goal the snapshot describes.
- ``narrative`` is the human-readable snapshot of present reality:
  non-empty, stripped, ≤ 5000 characters.
- ``captured_at`` is when reality was observed — timezone-aware UTC
  (``AGENTS.md`` §7). Snapshots are immutable once captured.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

MAX_NARRATIVE_LENGTH = 5000


class CurrentStateError(ValueError):
    """Raised when a CurrentState invariant is violated."""


@dataclass(frozen=True)
class CurrentState:
    """An immutable snapshot of present reality for a Goal."""

    state_id: uuid.UUID
    goal_id: uuid.UUID
    narrative: str
    captured_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.state_id, uuid.UUID):
            raise CurrentStateError("state_id must be a UUID")
        if not isinstance(self.goal_id, uuid.UUID):
            raise CurrentStateError("goal_id must be a UUID")
        narrative = self.narrative
        if not isinstance(narrative, str) or not narrative.strip():
            raise CurrentStateError("narrative must be a non-empty string")
        if len(narrative.strip()) > MAX_NARRATIVE_LENGTH:
            raise CurrentStateError(
                f"narrative must be at most {MAX_NARRATIVE_LENGTH} characters"
            )
        object.__setattr__(self, "narrative", narrative.strip())
        captured = self.captured_at
        if not isinstance(captured, datetime) or captured.tzinfo is None:
            raise CurrentStateError("captured_at must be timezone-aware")
        if captured.utcoffset() != timezone.utc.utcoffset(captured):
            raise CurrentStateError("captured_at must be in UTC")


def capture_current_state(
    goal_id: uuid.UUID,
    narrative: str,
    *,
    state_id: uuid.UUID | None = None,
    captured_at: datetime | None = None,
) -> CurrentState:
    """Capture a snapshot, generating identity and timestamp when omitted.

    ``state_id`` and ``captured_at`` may be injected for deterministic tests;
    ``captured_at`` must still be timezone-aware UTC.
    """
    return CurrentState(
        state_id=state_id if state_id is not None else uuid.uuid4(),
        goal_id=goal_id,
        narrative=narrative,
        captured_at=(
            captured_at if captured_at is not None else datetime.now(timezone.utc)
        ),
    )
