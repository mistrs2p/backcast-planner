"""Outcome decomposition use case — the AI half of pipeline step 11.

docs/04 step 11 asks for outcomes generated from the desired future
state; the LLM proposes them (ADR-002) and the deterministic half —
:func:`~backcasting.domain.outcome.define_outcome`, binding an
outcome to a plan — waits downstream. This use case wires the AI
half: the context builder assembles exactly the future state (the
destination is the only anchor a decomposition needs); the provider
port carries the request; the domain records the proposal verbatim,
tied to both the goal and the exact future state it decomposes.
Parsing the proposal into outcome titles is TASK-100's validation.

Failure is the port's one currency: vendor faults arrive as
:class:`~backcasting.domain.llm_provider.ProviderCallError` and
propagate untouched.
"""

from __future__ import annotations

from backcasting.application.context_builder import (
    build_outcome_decomposition_context,
)
from backcasting.domain.future_state import FutureState
from backcasting.domain.llm_provider import LLMProvider
from backcasting.domain.outcome_decomposition import (
    OutcomeDecomposition,
    record_outcome_decomposition,
)


def decompose_outcomes(
    future: FutureState,
    provider: LLMProvider,
) -> OutcomeDecomposition:
    """Ask ``provider`` to decompose ``future`` into outcomes and
    record the proposal.

    The decomposition is tied to the goal and the exact future
    state it reads, carries the provider's name and the model that
    actually answered, and is returned unsaved — persistence is the
    caller's wiring.
    """
    request = build_outcome_decomposition_context(future)
    response = provider.complete(request)
    return record_outcome_decomposition(
        future.goal_id,
        future.state_id,
        response.content,
        provider=provider.name,
        model=response.model,
    )
