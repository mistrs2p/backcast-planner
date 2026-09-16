"""Goal interpretation — the first AI proposal, on record.

docs/09 lists goal interpretation first among the AI operations:
the LLM reads the user's goal against their current state and
proposes what the goal actually means. ADR-002 draws the boundary
this module lives on: the LLM proposes, the domain validates and
enforces. So the proposal itself is kept verbatim — no parsing, no
sentiment, no pre-classified structure, for the same reason
:mod:`~backcasting.domain.feedback` keeps user statements verbatim:
a proposal the domain has already interpreted is a proposal the
reasoning layer can no longer see honestly. Schema validation is
the guardrail TASK-100 adds, upstream of the domain.

What the domain *does* own here is the record's integrity: the
proposal is non-empty and bounded, it is tied to the goal it
interprets, and it carries its provenance — which provider, which
model, when. An interpretation without provenance cannot be
audited (docs/09's audit-logging guardrail starts with this
record), and the model recorded is the one that *answered* (from
the response, not the request), because that is the fact.

Like every observation in this domain, an interpretation is an
immutable fact of history: no ``updated_at``, no revision path —
a re-interpretation is a new record.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from backcasting.domain.timezone import UTC, require_utc

MAX_PROPOSAL_LENGTH = 20_000
MAX_PROVIDER_LENGTH = 100
MAX_MODEL_LENGTH = 200


class GoalInterpretationError(ValueError):
    """Raised when a goal-interpretation invariant is violated."""


@dataclass(frozen=True)
class GoalInterpretation:
    """One AI proposal reading a goal, with its provenance."""

    interpretation_id: uuid.UUID
    goal_id: uuid.UUID
    proposal: str
    provider: str
    model: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.interpretation_id, uuid.UUID):
            raise GoalInterpretationError("interpretation_id must be a UUID")
        if not isinstance(self.goal_id, uuid.UUID):
            raise GoalInterpretationError("goal_id must be a UUID")
        proposal = self.proposal
        if (
            not isinstance(proposal, str)
            or not proposal.strip()
            or len(proposal) > MAX_PROPOSAL_LENGTH
        ):
            raise GoalInterpretationError(
                f"proposal must be a non-empty string of at most "
                f"{MAX_PROPOSAL_LENGTH} characters"
            )
        for name, bound in (
            ("provider", MAX_PROVIDER_LENGTH),
            ("model", MAX_MODEL_LENGTH),
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > bound
            ):
                raise GoalInterpretationError(
                    f"{name} must be a non-empty string of at most "
                    f"{bound} characters"
                )
        require_utc("created_at", self.created_at, error=GoalInterpretationError)


def record_goal_interpretation(
    goal_id: uuid.UUID,
    proposal: str,
    *,
    provider: str,
    model: str,
    created_at: datetime | None = None,
    interpretation_id: uuid.UUID | None = None,
) -> GoalInterpretation:
    """Record one interpretation of ``goal_id`` from ``provider``'s
    ``model``, verbatim and with provenance (default: now)."""
    return GoalInterpretation(
        interpretation_id=interpretation_id
        if interpretation_id is not None
        else uuid.uuid4(),
        goal_id=goal_id,
        proposal=proposal,
        provider=provider,
        model=model,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def interpretations_for_goal(
    interpretations: tuple[GoalInterpretation, ...],
    goal_id: uuid.UUID,
) -> tuple[GoalInterpretation, ...]:
    """The interpretations of one goal, earliest first.

    Input order is preserved; a re-interpretation is a new record,
    so the history reads chronologically as given.
    """
    if not isinstance(interpretations, tuple):
        raise GoalInterpretationError(
            "interpretations must be a tuple of GoalInterpretation"
        )
    for interpretation in interpretations:
        if not isinstance(interpretation, GoalInterpretation):
            raise GoalInterpretationError(
                "interpretations must be GoalInterpretation instances"
            )
    if not isinstance(goal_id, uuid.UUID):
        raise GoalInterpretationError("goal_id must be a UUID")
    return tuple(
        interpretation
        for interpretation in interpretations
        if interpretation.goal_id == goal_id
    )
