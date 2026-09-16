"""Strategy generation use case — the AI half of pipeline step 8.

docs/04 step 8 asks for candidate strategies; the LLM proposes them
(ADR-002) and the deterministic half —
:func:`~backcasting.domain.strategy.accept_proposed_strategies`,
binding proposals to a RUNNING run with unique names — already
waits downstream. This use case wires the AI half: the context
builder assembles the goal, the current state, and the future
state (the three anchors of every backcast); the provider port
carries the request to whichever vendor is wired; the domain
records the proposal verbatim with its provenance. Parsing the
proposal into :class:`~backcasting.domain.strategy.StrategyProposal`
tuples is TASK-100's validation, not this layer's.

Failure is the port's one currency: vendor faults arrive as
:class:`~backcasting.domain.llm_provider.ProviderCallError` and
propagate untouched.
"""

from __future__ import annotations

from backcasting.application.context_builder import build_strategy_context
from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import Goal
from backcasting.domain.llm_provider import LLMProvider
from backcasting.domain.strategy_generation import (
    StrategyGeneration,
    record_strategy_generation,
)


def generate_strategies(
    goal: Goal,
    state: CurrentState,
    future: FutureState,
    provider: LLMProvider,
) -> StrategyGeneration:
    """Ask ``provider`` for candidate strategies from ``state`` to
    ``future`` and record the proposal.

    The generation is tied to the goal, carries the provider's name
    and the model that actually answered, and is returned unsaved —
    persistence is the caller's wiring.
    """
    request = build_strategy_context(goal, state, future)
    response = provider.complete(request)
    return record_strategy_generation(
        goal.goal_id,
        response.content,
        provider=provider.name,
        model=response.model,
    )
