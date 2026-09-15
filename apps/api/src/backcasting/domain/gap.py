"""Gap domain model.

The Gap is the distance between present reality and the destination
(`docs/02-CONCEPTUAL-MODEL.md` "Planning Layer"): the backcasting pipeline
computes it as step 4, "Calculate Gap" (``docs/04-BACKCASTING-MODEL.md``).

This module defines the *shape* of that result. A Gap always ties together
one Current State snapshot and one Future State destination for a Goal,
carries a qualitative narrative, and may quantify the distance along zero
or more metric dimensions (:class:`GapDimension`) — a metric with its
current and target values. How those values are derived is the gap
*calculation* concern (a separate task); here we only pin what a recorded
Gap must satisfy.

Rules:

- IDs are UUIDs; ``goal_id``/``current_state_id``/``future_state_id``
  reference the entities the gap was computed from.
- ``narrative`` is the qualitative distance: optional, stripped,
  ≤ 5000 characters.
- Each dimension's ``current_value`` and ``target_value`` are validated
  against its metric; metric names are unique within a gap.
- ``calculated_at`` is timezone-aware UTC.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from backcasting.domain.metric import Metric, MetricError

MAX_NARRATIVE_LENGTH = 5000


class GapError(ValueError):
    """Raised when a Gap invariant is violated."""


@dataclass(frozen=True)
class GapDimension:
    """One quantified axis of a gap: a metric's current vs target value."""

    metric: Metric
    current_value: object
    target_value: object

    def __post_init__(self) -> None:
        if not isinstance(self.metric, Metric):
            raise GapError("dimension metric must be a Metric")
        try:
            object.__setattr__(
                self, "current_value", self.metric.validate(self.current_value)
            )
            object.__setattr__(
                self, "target_value", self.metric.validate(self.target_value)
            )
        except MetricError as exc:
            raise GapError(f"dimension values invalid: {exc}") from exc


@dataclass(frozen=True)
class Gap:
    """The recorded distance between a current state and a future state."""

    gap_id: uuid.UUID
    goal_id: uuid.UUID
    current_state_id: uuid.UUID
    future_state_id: uuid.UUID
    calculated_at: datetime
    dimensions: tuple[GapDimension, ...] = ()
    narrative: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.gap_id, uuid.UUID):
            raise GapError("gap_id must be a UUID")
        if not isinstance(self.goal_id, uuid.UUID):
            raise GapError("goal_id must be a UUID")
        if not isinstance(self.current_state_id, uuid.UUID):
            raise GapError("current_state_id must be a UUID")
        if not isinstance(self.future_state_id, uuid.UUID):
            raise GapError("future_state_id must be a UUID")
        if not isinstance(self.dimensions, tuple):
            raise GapError("dimensions must be a tuple")
        seen_names: set[str] = set()
        for dimension in self.dimensions:
            if not isinstance(dimension, GapDimension):
                raise GapError("dimensions must contain GapDimension instances")
            if dimension.metric.name in seen_names:
                raise GapError(
                    f"duplicate metric in gap: {dimension.metric.name}"
                )
            seen_names.add(dimension.metric.name)
        narrative = self.narrative
        if narrative is None:
            narrative = ""
        if not isinstance(narrative, str):
            raise GapError("narrative must be a string")
        if len(narrative.strip()) > MAX_NARRATIVE_LENGTH:
            raise GapError(
                f"narrative must be at most {MAX_NARRATIVE_LENGTH} characters"
            )
        object.__setattr__(self, "narrative", narrative.strip())
        calculated = self.calculated_at
        if not isinstance(calculated, datetime) or calculated.tzinfo is None:
            raise GapError("calculated_at must be timezone-aware")
        if calculated.utcoffset() != timezone.utc.utcoffset(calculated):
            raise GapError("calculated_at must be in UTC")


def record_gap(
    goal_id: uuid.UUID,
    current_state_id: uuid.UUID,
    future_state_id: uuid.UUID,
    *,
    dimensions: tuple[GapDimension, ...] = (),
    narrative: str = "",
    gap_id: uuid.UUID | None = None,
    calculated_at: datetime | None = None,
) -> Gap:
    """Record a gap, generating identity and timestamp when omitted.

    ``gap_id`` and ``calculated_at`` may be injected for deterministic
    tests; ``calculated_at`` must still be timezone-aware UTC.
    """
    return Gap(
        gap_id=gap_id if gap_id is not None else uuid.uuid4(),
        goal_id=goal_id,
        current_state_id=current_state_id,
        future_state_id=future_state_id,
        dimensions=dimensions,
        narrative=narrative,
        calculated_at=(
            calculated_at
            if calculated_at is not None
            else datetime.now(timezone.utc)
        ),
    )
