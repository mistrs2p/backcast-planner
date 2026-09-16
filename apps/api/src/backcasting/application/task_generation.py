"""Task generation use case — the AI half of pipeline step 12.

docs/04 step 12 asks for tasks generated from outcomes; the LLM
proposes them (ADR-002) and the deterministic half —
:func:`~backcasting.domain.task.accept_proposed_tasks`, binding
:class:`~backcasting.domain.task.TaskProposal` batches to a living
plan with resolved outcome links — waits downstream. This use case
wires the AI half: the context builder assembles exactly the
outcomes (the achievements to be decomposed into units of action);
the provider port carries the request to whichever vendor is wired;
the domain records the proposal verbatim with its provenance, tied
to the plan those outcomes serve. Parsing the proposal into
TaskProposal tuples is TASK-100's validation, not this layer's.

Failure is the port's one currency: vendor faults arrive as
:class:`~backcasting.domain.llm_provider.ProviderCallError` and
propagate untouched.
"""

from __future__ import annotations

from backcasting.application.context_builder import build_task_generation_context
from backcasting.domain.llm_provider import LLMProvider
from backcasting.domain.outcome import Outcome
from backcasting.domain.task_generation import (
    TaskGeneration,
    TaskGenerationError,
    record_task_generation,
)


def generate_tasks(
    outcomes: tuple[Outcome, ...],
    provider: LLMProvider,
) -> TaskGeneration:
    """Ask ``provider`` to decompose ``outcomes`` into tasks and
    record the proposal.

    The outcomes must be a non-empty tuple sharing one plan — tasks
    are proposed for a single plan's shape, and the record is anchored
    to that plan. The generation carries the provider's name and the
    model that actually answered, and is returned unsaved —
    persistence is the caller's wiring.
    """
    if not isinstance(outcomes, tuple):
        raise TaskGenerationError("outcomes must be a tuple of Outcome")
    for outcome in outcomes:
        if not isinstance(outcome, Outcome):
            raise TaskGenerationError("outcomes must be Outcome instances")
    if not outcomes:
        raise TaskGenerationError(
            "at least one outcome is required — no anchor to generate from"
        )
    plan_id = outcomes[0].plan_id
    for outcome in outcomes[1:]:
        if outcome.plan_id != plan_id:
            raise TaskGenerationError(
                "outcomes must share one plan — a generation is anchored "
                "to a single plan"
            )
    request = build_task_generation_context(outcomes)
    response = provider.complete(request)
    return record_task_generation(
        plan_id,
        response.content,
        provider=provider.name,
        model=response.model,
    )
