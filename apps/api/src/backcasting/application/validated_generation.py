"""Validated generation — schema validation with retry limits
(docs/09).

docs/09's guardrails pair *schema validation* with *retry limits*:
a proposal that fails its schema is not accepted, and the provider
gets a bounded number of chances to produce one that passes. This
use-case layer wires the two: it asks the provider through the
operation's context, parses the answer with the
:mod:`~backcasting.domain.proposal_parsing` schemas, and on a parse
failure asks again — up to ``max_attempts`` (default 3), after
which the last parse error propagates, chained. Only the attempt
that parses is recorded verbatim with its provenance; the rejected
attempts leave no record, because they were never accepted.

Vendor faults are not retried here: a
:class:`~backcasting.domain.llm_provider.ProviderCallError` is a
transport failure, and what to do about one — retry, fall back, or
surface — is TASK-103's fallback policy, not this layer's. It
propagates untouched from the first attempt.

The parsed proposals are returned alongside the record, but
acceptance remains the caller's explicit step —
:func:`~backcasting.domain.strategy.accept_proposed_strategies`
and :func:`~backcasting.domain.task.accept_proposed_tasks` apply
the domain rules with the run/plan context only the caller holds.
"""

from __future__ import annotations

from collections.abc import Callable

from backcasting.application.context_builder import (
    build_strategy_context,
    build_outcome_decomposition_context,
    build_task_generation_context,
)
from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import Goal
from backcasting.domain.llm_provider import LLMProvider, LLMResponse
from backcasting.domain.outcome import Outcome
from backcasting.domain.outcome_decomposition import (
    OutcomeDecomposition,
    record_outcome_decomposition,
)
from backcasting.domain.proposal_parsing import (
    ProposalParseError,
    parse_outcome_titles,
    parse_strategy_proposals,
    parse_task_proposals,
)
from backcasting.domain.strategy import StrategyProposal
from backcasting.domain.strategy_generation import (
    StrategyGeneration,
    record_strategy_generation,
)
from backcasting.domain.task import TaskProposal
from backcasting.domain.task_generation import (
    plan_anchor,
    record_task_generation,
)

DEFAULT_MAX_ATTEMPTS = 3


def _attempt(
    ask: Callable[[], LLMResponse],
    parse: Callable[[str], object],
    max_attempts: int,
) -> tuple[LLMResponse, object]:
    """Ask until ``parse`` accepts the answer, within
    ``max_attempts``."""
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
        raise ValueError("max_attempts must be a positive integer")
    if max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    last_error: ProposalParseError | None = None
    for _ in range(max_attempts):
        response = ask()
        try:
            return response, parse(response.content)
        except ProposalParseError as error:
            last_error = error
    raise ProposalParseError(
        f"provider did not produce a schema-valid proposal within "
        f"{max_attempts} attempts"
    ) from last_error


def generate_validated_strategies(
    goal: Goal,
    state: CurrentState,
    future: FutureState,
    provider: LLMProvider,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> tuple[StrategyGeneration, tuple[StrategyProposal, ...]]:
    """Ask ``provider`` for strategies until one parses; return the
    verbatim record and the parsed proposals (unsaved)."""
    request = build_strategy_context(goal, state, future)
    response, proposals = _attempt(
        lambda: provider.complete(request),
        parse_strategy_proposals,
        max_attempts,
    )
    record = record_strategy_generation(
        goal.goal_id,
        response.content,
        provider=provider.name,
        model=response.model,
    )
    return record, proposals  # type: ignore[return-value]


def generate_validated_outcomes(
    future: FutureState,
    provider: LLMProvider,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> tuple[OutcomeDecomposition, tuple[str, ...]]:
    """Ask ``provider`` to decompose ``future`` until the answer
    parses; return the verbatim record and the outcome titles
    (unsaved)."""
    request = build_outcome_decomposition_context(future)
    response, titles = _attempt(
        lambda: provider.complete(request),
        parse_outcome_titles,
        max_attempts,
    )
    record = record_outcome_decomposition(
        future.goal_id,
        future.state_id,
        response.content,
        provider=provider.name,
        model=response.model,
    )
    return record, titles  # type: ignore[return-value]


def generate_validated_tasks(
    outcomes: tuple[Outcome, ...],
    provider: LLMProvider,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> tuple[TaskGeneration, tuple[TaskProposal, ...]]:
    """Ask ``provider`` to decompose ``outcomes`` into tasks until
    the answer parses; return the verbatim record and the parsed
    proposals (unsaved).

    The outcomes must satisfy :func:`~backcasting.domain.task_generation.plan_anchor`'s
    rule — a non-empty tuple sharing one plan; that anchor is the
    record's.
    """
    plan_id = plan_anchor(outcomes)
    request = build_task_generation_context(outcomes)
    response, proposals = _attempt(
        lambda: provider.complete(request),
        parse_task_proposals,
        max_attempts,
    )
    record = record_task_generation(
        plan_id,
        response.content,
        provider=provider.name,
        model=response.model,
    )
    return record, proposals  # type: ignore[return-value]
