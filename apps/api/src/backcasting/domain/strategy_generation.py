"""Strategy generation — the AI half of pipeline step 8.

docs/04's pipeline generates candidate strategies (step 8) and
selects one (step 9); docs/02 calls a Strategy the "method of
movement". The deterministic half already exists:
:func:`~backcasting.domain.strategy.accept_proposed_strategies`
turns raw proposals into run-bound candidates, and
:func:`~backcasting.domain.strategy.decide_strategy` selects. What
this module records is the other half — the LLM's generation
itself, kept verbatim with its provenance, exactly as
:mod:`~backcasting.domain.goal_interpretation` keeps an
interpretation: the domain does not parse the proposal here
(schema validation is TASK-100's guardrail), because a proposal
the domain has already interpreted is a proposal the reasoning
layer can no longer see honestly (ADR-002).

The record is tied to the goal the strategies serve; the run
binding happens at acceptance, where the deterministic rules
(a RUNNING run, unique names, non-empty batches) apply. Like
every observation, a generation is an immutable fact of history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from backcasting.domain.timezone import UTC, require_utc

MAX_PROPOSAL_LENGTH = 20_000
MAX_PROVIDER_LENGTH = 100
MAX_MODEL_LENGTH = 200


class StrategyGenerationError(ValueError):
    """Raised when a strategy-generation invariant is violated."""


@dataclass(frozen=True)
class StrategyGeneration:
    """One AI proposal generating candidate strategies, verbatim,
    with its provenance."""

    generation_id: uuid.UUID
    goal_id: uuid.UUID
    proposal: str
    provider: str
    model: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.generation_id, uuid.UUID):
            raise StrategyGenerationError("generation_id must be a UUID")
        if not isinstance(self.goal_id, uuid.UUID):
            raise StrategyGenerationError("goal_id must be a UUID")
        proposal = self.proposal
        if (
            not isinstance(proposal, str)
            or not proposal.strip()
            or len(proposal) > MAX_PROPOSAL_LENGTH
        ):
            raise StrategyGenerationError(
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
                raise StrategyGenerationError(
                    f"{name} must be a non-empty string of at most "
                    f"{bound} characters"
                )
        require_utc("created_at", self.created_at, error=StrategyGenerationError)


def record_strategy_generation(
    goal_id: uuid.UUID,
    proposal: str,
    *,
    provider: str,
    model: str,
    created_at: datetime | None = None,
    generation_id: uuid.UUID | None = None,
) -> StrategyGeneration:
    """Record one strategy generation for ``goal_id`` from
    ``provider``'s ``model``, verbatim and with provenance
    (default: now)."""
    return StrategyGeneration(
        generation_id=generation_id
        if generation_id is not None
        else uuid.uuid4(),
        goal_id=goal_id,
        proposal=proposal,
        provider=provider,
        model=model,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def generations_for_goal(
    generations: tuple[StrategyGeneration, ...],
    goal_id: uuid.UUID,
) -> tuple[StrategyGeneration, ...]:
    """The strategy generations of one goal, in input order."""
    if not isinstance(generations, tuple):
        raise StrategyGenerationError(
            "generations must be a tuple of StrategyGeneration"
        )
    for generation in generations:
        if not isinstance(generation, StrategyGeneration):
            raise StrategyGenerationError(
                "generations must be StrategyGeneration instances"
            )
    if not isinstance(goal_id, uuid.UUID):
        raise StrategyGenerationError("goal_id must be a UUID")
    return tuple(
        generation
        for generation in generations
        if generation.goal_id == goal_id
    )
