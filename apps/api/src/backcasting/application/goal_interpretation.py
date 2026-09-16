"""Goal interpretation use case — the first AI operation wired.

Composes what TASK-090 through TASK-094 built into docs/09's first
operation: the context builder assembles exactly the goal and the
current state, the provider port carries the request to whichever
vendor is wired, and the domain records the proposal verbatim with
its provenance. The application layer's whole contribution is the
wiring — every rule in the chain belongs to the domain, every
proposal to the LLM, and nothing here interprets either
(ADR-002).

Failure is the port's one currency: a vendor fault arrives as
:class:`~backcasting.domain.llm_provider.ProviderCallError` and
propagates untouched, so the caller (and the fallback logic of
TASK-103, later) can catch one type.
"""

from __future__ import annotations

from backcasting.application.context_builder import (
    build_goal_interpretation_context,
)
from backcasting.domain.current_state import CurrentState
from backcasting.domain.goal import Goal
from backcasting.domain.goal_interpretation import (
    GoalInterpretation,
    record_goal_interpretation,
)
from backcasting.domain.llm_provider import LLMProvider


def interpret_goal(
    goal: Goal,
    state: CurrentState,
    provider: LLMProvider,
) -> GoalInterpretation:
    """Ask ``provider`` to interpret ``goal`` against ``state`` and
    record the proposal.

    The interpretation is tied to the goal it reads, carries the
    provider's name and the model that actually answered, and is
    returned unsaved — persistence is the caller's wiring.
    """
    request = build_goal_interpretation_context(goal, state)
    response = provider.complete(request)
    return record_goal_interpretation(
        goal.goal_id,
        response.content,
        provider=provider.name,
        model=response.model,
    )
