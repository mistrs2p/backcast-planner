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
from backcasting.domain.future_state import FutureState

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


@dataclass(frozen=True)
class MilestoneProposal:
    """A raw milestone proposal as an AI adapter emits it.

    The domain does not generate milestones (``docs/09-AI-ARCHITECTURE.md``:
    "The LLM proposes and reasons; the Domain validates and enforces");
    it accepts proposals through :func:`accept_proposed_milestones`,
    which applies the deterministic rules.
    """

    title: str
    target_date: datetime
    description: str = ""

    def __post_init__(self) -> None:
        title = self.title
        if not isinstance(title, str) or not title.strip():
            raise MilestoneError("proposal title must be a non-empty string")
        if len(title.strip()) > MAX_TITLE_LENGTH:
            raise MilestoneError(
                f"proposal title must be at most {MAX_TITLE_LENGTH} characters"
            )
        object.__setattr__(self, "title", title.strip())
        target_date = self.target_date
        if not isinstance(target_date, datetime) or target_date.tzinfo is None:
            raise MilestoneError("proposal target_date must be timezone-aware")
        if target_date.utcoffset() != timezone.utc.utcoffset(target_date):
            raise MilestoneError("proposal target_date must be in UTC")
        object.__setattr__(self, "target_date", target_date)
        description = self.description
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise MilestoneError("proposal description must be a string")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise MilestoneError(
                f"proposal description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        object.__setattr__(self, "description", description)


def accept_proposed_milestones(
    run: BackcastingRun,
    future_state: FutureState,
    proposals: tuple[MilestoneProposal, ...],
    *,
    at: datetime | None = None,
) -> tuple[Milestone, ...]:
    """Accept AI-proposed milestones for a run (pipeline step 10).

    Deterministic rules enforced here:

    - The run must be RUNNING (milestones are generated during the run).
    - ``future_state`` must be exactly the destination the run is
      backcasting from (same state id and goal) — a milestone path
      belongs to one destination.
    - At least one proposal must be supplied — an empty generation is a
      failed step, not a valid outcome.
    - Titles must be unique within the batch.
    - Target dates must be strictly increasing: milestones are ordered
      checkpoints along the path.
    - Every target date must lie strictly between the acceptance
      instant and the destination's target date — intermediate
      checkpoints, never the destination itself.

    Returns the recorded milestones in proposal order, sharing ``at`` as
    their creation time.
    """
    if not isinstance(run, BackcastingRun):
        raise TypeError("run must be a BackcastingRun")
    if not isinstance(future_state, FutureState):
        raise TypeError("future_state must be a FutureState")
    if not isinstance(proposals, tuple):
        raise MilestoneError("proposals must be a tuple of MilestoneProposal")
    if run.status is not BackcastingRunStatus.RUNNING:
        raise MilestoneError(
            f"cannot accept milestones for a run with status {run.status.value}"
        )
    if future_state.state_id != run.future_state_id:
        raise MilestoneError(
            "future_state must be the destination this run is backcasting from"
        )
    if future_state.goal_id != run.goal_id:
        raise MilestoneError("future_state must belong to the run's goal")
    if not proposals:
        raise MilestoneError("at least one milestone proposal is required")
    now = at if at is not None else datetime.now(timezone.utc)
    titles: set[str] = set()
    previous_target: datetime | None = None
    for proposal in proposals:
        if not isinstance(proposal, MilestoneProposal):
            raise MilestoneError("proposals must be MilestoneProposal instances")
        if proposal.title in titles:
            raise MilestoneError(f"duplicate milestone title: {proposal.title}")
        titles.add(proposal.title)
        if previous_target is not None and proposal.target_date <= previous_target:
            raise MilestoneError("milestone target dates must be strictly increasing")
        previous_target = proposal.target_date
        if proposal.target_date >= future_state.target_date:
            raise MilestoneError(
                "milestone target dates must precede the destination's target date"
            )
    return tuple(
        define_milestone(
            run,
            proposal.title,
            proposal.target_date,
            description=proposal.description,
            created_at=now,
        )
        for proposal in proposals
    )
