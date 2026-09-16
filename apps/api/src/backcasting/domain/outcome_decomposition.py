"""Outcome decomposition — the AI half of pipeline step 11.

docs/04's pipeline generates outcomes (step 11) from the desired
future state; docs/02 calls an Outcome an "achieved state/result".
The deterministic half is :func:`~backcasting.domain.outcome.define_outcome`,
which binds an outcome to a plan; what this module records is the
LLM's decomposition itself — the future state read as the outcomes
that must exist for it to hold — kept verbatim with its
provenance, exactly as
:mod:`~backcasting.domain.goal_interpretation` and
:mod:`~backcasting.domain.strategy_generation` keep their
proposals: the domain does not parse it here (schema validation is
TASK-100's guardrail), because a proposal the domain has already
interpreted is a proposal the reasoning layer can no longer see
honestly (ADR-002).

The record is tied to both the goal and the exact future state it
decomposes — a re-derived future state deserves a fresh
decomposition, and the audit trail must show which destination the
outcomes were read against. Like every observation, a
decomposition is an immutable fact of history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from backcasting.domain.timezone import UTC, require_utc

MAX_PROPOSAL_LENGTH = 20_000
MAX_PROVIDER_LENGTH = 100
MAX_MODEL_LENGTH = 200


class OutcomeDecompositionError(ValueError):
    """Raised when an outcome-decomposition invariant is violated."""


@dataclass(frozen=True)
class OutcomeDecomposition:
    """One AI proposal decomposing a future state into outcomes,
    verbatim, with its provenance."""

    decomposition_id: uuid.UUID
    goal_id: uuid.UUID
    future_state_id: uuid.UUID
    proposal: str
    provider: str
    model: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.decomposition_id, uuid.UUID):
            raise OutcomeDecompositionError("decomposition_id must be a UUID")
        for name in ("goal_id", "future_state_id"):
            if not isinstance(getattr(self, name), uuid.UUID):
                raise OutcomeDecompositionError(f"{name} must be a UUID")
        proposal = self.proposal
        if (
            not isinstance(proposal, str)
            or not proposal.strip()
            or len(proposal) > MAX_PROPOSAL_LENGTH
        ):
            raise OutcomeDecompositionError(
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
                raise OutcomeDecompositionError(
                    f"{name} must be a non-empty string of at most "
                    f"{bound} characters"
                )
        require_utc("created_at", self.created_at, error=OutcomeDecompositionError)


def record_outcome_decomposition(
    goal_id: uuid.UUID,
    future_state_id: uuid.UUID,
    proposal: str,
    *,
    provider: str,
    model: str,
    created_at: datetime | None = None,
    decomposition_id: uuid.UUID | None = None,
) -> OutcomeDecomposition:
    """Record one decomposition of ``future_state_id`` from
    ``provider``'s ``model``, verbatim and with provenance
    (default: now)."""
    return OutcomeDecomposition(
        decomposition_id=decomposition_id
        if decomposition_id is not None
        else uuid.uuid4(),
        goal_id=goal_id,
        future_state_id=future_state_id,
        proposal=proposal,
        provider=provider,
        model=model,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def decompositions_for_future(
    decompositions: tuple[OutcomeDecomposition, ...],
    future_state_id: uuid.UUID,
) -> tuple[OutcomeDecomposition, ...]:
    """The decompositions of one future state, in input order."""
    if not isinstance(decompositions, tuple):
        raise OutcomeDecompositionError(
            "decompositions must be a tuple of OutcomeDecomposition"
        )
    for decomposition in decompositions:
        if not isinstance(decomposition, OutcomeDecomposition):
            raise OutcomeDecompositionError(
                "decompositions must be OutcomeDecomposition instances"
            )
    if not isinstance(future_state_id, uuid.UUID):
        raise OutcomeDecompositionError("future_state_id must be a UUID")
    return tuple(
        decomposition
        for decomposition in decompositions
        if decomposition.future_state_id == future_state_id
    )
