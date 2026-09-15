"""Milestone domain model.

A Milestone is an "intermediate measurable checkpoint"
(``docs/02-CONCEPTUAL-MODEL.md`` "Planning Layer") on the path from the
current state to the desired future. The backcasting pipeline generates
milestones after the strategy is selected (``docs/04-BACKCASTING-MODEL.md``
step 10), so — like strategies — milestones are defined against a
backcasting run.

Rules:

- IDs are UUIDs; ``run_id``/``goal_id`` reference the run that generated
  the milestone and the goal it serves. The Plan 1:N Milestones link
  (docs/03) is established when the Plan model exists.
- ``title`` is non-empty, stripped, ≤ 200 characters; ``description`` is
  optional free text ≤ 5000 characters.
- ``target_date`` is a timezone-aware UTC instant strictly after
  ``created_at``: a checkpoint lies ahead of its definition, mirroring
  how a FutureState anchors its target after creation.
- A milestone carries no lifecycle of its own: as a *measurable*
  checkpoint, its achievement is expressed through its Outcomes
  (Milestone 1:N Outcomes, docs/03) rather than a status flag.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
- :func:`define_milestone` only accepts a RUNNING run whose goal the
  milestone is bound to — milestones are generated *during* a run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backcasting.domain.backcasting_run import BackcastingRun, BackcastingRunStatus

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000


class MilestoneError(ValueError):
    """Raised when a Milestone invariant is violated."""


@dataclass(frozen=True)
class Milestone:
    """An intermediate measurable checkpoint toward a goal's destination."""

    milestone_id: uuid.UUID
    run_id: uuid.UUID
    goal_id: uuid.UUID
    title: str
    target_date: datetime
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.milestone_id, uuid.UUID):
            raise MilestoneError("milestone_id must be a UUID")
        if not isinstance(self.run_id, uuid.UUID):
            raise MilestoneError("run_id must be a UUID")
        if not isinstance(self.goal_id, uuid.UUID):
            raise MilestoneError("goal_id must be a UUID")
        title = self.title
        if not isinstance(title, str) or not title.strip():
            raise MilestoneError("title must be a non-empty string")
        if len(title.strip()) > MAX_TITLE_LENGTH:
            raise MilestoneError(f"title must be at most {MAX_TITLE_LENGTH} characters")
        object.__setattr__(self, "title", title.strip())
        description = self.description
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise MilestoneError("description must be a string")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise MilestoneError(
                f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        object.__setattr__(self, "description", description)
        for stamp_name in ("target_date", "created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise MilestoneError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise MilestoneError(f"{stamp_name} must be in UTC")
        if self.target_date <= self.created_at:
            raise MilestoneError("target_date must be after created_at")
        if self.updated_at < self.created_at:
            raise MilestoneError("updated_at must not precede created_at")


def define_milestone(
    run: BackcastingRun,
    title: str,
    target_date: datetime,
    *,
    description: str = "",
    milestone_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Milestone:
    """Define a milestone during a RUNNING run, bound to the run's goal.

    The run must still be running (milestones are generated as part of
    the pipeline, after strategy selection) and the target date must lie
    strictly after the milestone's creation time.
    """
    if not isinstance(run, BackcastingRun):
        raise TypeError("run must be a BackcastingRun")
    if run.status is not BackcastingRunStatus.RUNNING:
        raise MilestoneError(
            f"cannot define milestones for a run with status {run.status.value}"
        )
    now = created_at if created_at is not None else datetime.now(timezone.utc)
    return Milestone(
        milestone_id=milestone_id if milestone_id is not None else uuid.uuid4(),
        run_id=run.run_id,
        goal_id=run.goal_id,
        title=title,
        target_date=target_date,
        description=description,
        created_at=now,
        updated_at=now,
    )
