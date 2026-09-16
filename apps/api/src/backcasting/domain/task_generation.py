"""Task generation — the AI half of pipeline step 12.

docs/04's pipeline generates tasks from outcomes (step 12); docs/02
calls a Task the "unit of action". The deterministic half already
exists: :func:`~backcasting.domain.task.accept_proposed_tasks` turns
raw :class:`~backcasting.domain.task.TaskProposal` batches into
plan-bound tasks with resolved outcome links. What this module
records is the other half — the LLM's generation itself, kept
verbatim with its provenance, exactly as
:mod:`~backcasting.domain.goal_interpretation`,
:mod:`~backcasting.domain.strategy_generation`, and
:mod:`~backcasting.domain.outcome_decomposition` keep their
proposals: the domain does not parse it here (schema validation is
TASK-100's guardrail), because a proposal the domain has already
interpreted is a proposal the reasoning layer can no longer see
honestly (ADR-002).

The record is tied to the plan the generation serves — the outcomes
handed to the LLM belong to one plan, and the audit trail must show
which plan's shape the tasks were proposed against. Like every
observation, a generation is an immutable fact of history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from backcasting.domain.timezone import UTC, require_utc

MAX_PROPOSAL_LENGTH = 20_000
MAX_PROVIDER_LENGTH = 100
MAX_MODEL_LENGTH = 200


class TaskGenerationError(ValueError):
    """Raised when a task-generation invariant is violated."""


@dataclass(frozen=True)
class TaskGeneration:
    """One AI proposal generating tasks from outcomes, verbatim,
    with its provenance."""

    generation_id: uuid.UUID
    plan_id: uuid.UUID
    proposal: str
    provider: str
    model: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.generation_id, uuid.UUID):
            raise TaskGenerationError("generation_id must be a UUID")
        if not isinstance(self.plan_id, uuid.UUID):
            raise TaskGenerationError("plan_id must be a UUID")
        proposal = self.proposal
        if (
            not isinstance(proposal, str)
            or not proposal.strip()
            or len(proposal) > MAX_PROPOSAL_LENGTH
        ):
            raise TaskGenerationError(
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
                raise TaskGenerationError(
                    f"{name} must be a non-empty string of at most "
                    f"{bound} characters"
                )
        require_utc("created_at", self.created_at, error=TaskGenerationError)


def record_task_generation(
    plan_id: uuid.UUID,
    proposal: str,
    *,
    provider: str,
    model: str,
    created_at: datetime | None = None,
    generation_id: uuid.UUID | None = None,
) -> TaskGeneration:
    """Record one task generation for ``plan_id`` from ``provider``'s
    ``model``, verbatim and with provenance (default: now)."""
    return TaskGeneration(
        generation_id=generation_id
        if generation_id is not None
        else uuid.uuid4(),
        plan_id=plan_id,
        proposal=proposal,
        provider=provider,
        model=model,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def generations_for_plan(
    generations: tuple[TaskGeneration, ...],
    plan_id: uuid.UUID,
) -> tuple[TaskGeneration, ...]:
    """The task generations of one plan, in input order."""
    if not isinstance(generations, tuple):
        raise TaskGenerationError(
            "generations must be a tuple of TaskGeneration"
        )
    for generation in generations:
        if not isinstance(generation, TaskGeneration):
            raise TaskGenerationError(
                "generations must be TaskGeneration instances"
            )
    if not isinstance(plan_id, uuid.UUID):
        raise TaskGenerationError("plan_id must be a UUID")
    return tuple(
        generation
        for generation in generations
        if generation.plan_id == plan_id
    )
