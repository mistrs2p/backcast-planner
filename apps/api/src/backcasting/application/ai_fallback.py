"""The fallback policy — which AI failures degrade, and to what
(TASK-103).

Every AI operation in this system has a deterministic alternative:
strategies, outcomes, and tasks can be proposed by hand and
accepted through the same deterministic rules. That makes
degradation a *designed* path, not an apology — and this module
decides when it is taken:

- A vendor fault (:class:`~backcasting.domain.llm_provider.ProviderCallError`)
  falls back: the provider is down, the plan is not.
- A proposal that never validated
  (:class:`~backcasting.domain.proposal_parsing.ProposalParseError`,
  already retried to its limit by
  :mod:`~backcasting.application.validated_generation`) falls
  back: the model kept answering outside its schema, and the human
  path is the honest next step.
- A permission denial
  (:class:`~backcasting.domain.tool_permissions.ToolPermissionError`)
  does **not** fall back: the allowlist said no, and quietly
  switching to manual entry would turn a configuration error into
  a silent behavior change. It surfaces.
- A programming error
  (:class:`~backcasting.domain.llm_provider.LLMProviderError`)
  does not fall back either, for the same reason: bugs must be
  loud.

Each wrapper returns the validated generation's result and
``None`` on success, or ``None`` and the
:class:`~backcasting.domain.ai_fallback.Fallback` recording why
the deterministic path must take over. The verbatim proposal
records are only ever written for attempts that parsed — a
fallback leaves no proposal record, only its reason.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from backcasting.application.validated_generation import (
    generate_validated_outcomes,
    generate_validated_strategies,
    generate_validated_tasks,
)
from backcasting.domain.ai_fallback import Fallback
from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import Goal
from backcasting.domain.llm_provider import LLMProvider, ProviderCallError
from backcasting.domain.outcome import Outcome
from backcasting.domain.outcome_decomposition import OutcomeDecomposition
from backcasting.domain.proposal_parsing import ProposalParseError
from backcasting.domain.strategy import StrategyProposal
from backcasting.domain.strategy_generation import StrategyGeneration
from backcasting.domain.task import TaskProposal
from backcasting.domain.task_generation import TaskGeneration

T = TypeVar("T")

FALLS_BACK_ON = (ProviderCallError, ProposalParseError)
"""The failures that take the deterministic path: vendor faults and
proposals that never validated."""


def _with_fallback(call: Callable[[], T]) -> tuple[T | None, Fallback | None]:
    try:
        return call(), None
    except FALLS_BACK_ON as error:
        return None, Fallback(f"{type(error).__name__}: {error}")


def attempt_strategies(
    goal: Goal,
    state: CurrentState,
    future: FutureState,
    provider: LLMProvider,
    *,
    max_attempts: int = 3,
) -> tuple[tuple[StrategyGeneration, tuple[StrategyProposal, ...]] | None, Fallback | None]:
    """Try the AI path for strategies; on a fallback-worthy failure,
    return the reason the deterministic path must take over."""
    return _with_fallback(
        lambda: generate_validated_strategies(
            goal, state, future, provider, max_attempts=max_attempts
        )
    )


def attempt_outcomes(
    future: FutureState,
    provider: LLMProvider,
    *,
    max_attempts: int = 3,
) -> tuple[tuple[OutcomeDecomposition, tuple[str, ...]] | None, Fallback | None]:
    """Try the AI path for outcome decomposition; on a
    fallback-worthy failure, return the reason."""
    return _with_fallback(
        lambda: generate_validated_outcomes(
            future, provider, max_attempts=max_attempts
        )
    )


def attempt_tasks(
    outcomes: tuple[Outcome, ...],
    provider: LLMProvider,
    *,
    max_attempts: int = 3,
) -> tuple[tuple[TaskGeneration, tuple[TaskProposal, ...]] | None, Fallback | None]:
    """Try the AI path for task generation; on a fallback-worthy
    failure, return the reason."""
    return _with_fallback(
        lambda: generate_validated_tasks(
            outcomes, provider, max_attempts=max_attempts
        )
    )
