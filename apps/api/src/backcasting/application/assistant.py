"""AI assistant use cases (TASK-116) — docs/09's operations, wired.

The assistant's first capability in the product: goal interpretation,
the pipeline's entry operation. The chain is entirely built in the
layers below — the context builder sends exactly the goal and the
current state (docs/09's context strategy), the provider port
carries the request to whichever vendor is wired, and the domain
records the proposal verbatim with its provenance (ADR-002: the LLM
proposes, the domain validates). This service's whole contribution
is the wiring and the honest failure states:

- No provider configured is not an error to hide: the server was
  assembled without an LLM (the default — vendor adapters are
  optional dependencies), and the assistant says so rather than
  pretending. The remaining operations (clarification, strategies,
  outcomes, tasks, explanations) ride the same pattern as their
  acceptance flows join the product.
- A vendor fault surfaces as the port's one failure currency,
  :class:`~backcasting.domain.llm_provider.ProviderCallError` —
  there is no deterministic alternative for *reading* a goal, so
  unlike strategies/outcomes/tasks (``ai_fallback``) there is
  nothing to fall back to.
"""

from __future__ import annotations

import uuid

from backcasting.application.context_builder import (
    build_goal_interpretation_context,
)
from backcasting.application.goals import GoalNotFoundError
from backcasting.domain.goal import Goal
from backcasting.domain.goal_interpretation import (
    GoalInterpretation,
    record_goal_interpretation,
)
from backcasting.domain.llm_provider import LLMProvider
from backcasting.domain.repositories import (
    CurrentStateRepository,
    GoalInterpretationRepository,
    GoalRepository,
)


class NoProviderError(Exception):
    """Raised when the assistant is asked to work without an LLM —
    the server was assembled without a provider wired, and the
    caller deserves the honest state, not a silent refusal."""


class NoCurrentStateError(LookupError):
    """Raised when the goal has no current state to interpret
    against — define the backcast first."""


class AssistantService:
    """The AI assistant over the goal's records."""

    def __init__(
        self,
        goals: GoalRepository,
        states: CurrentStateRepository,
        interpretations: GoalInterpretationRepository,
        provider: LLMProvider | None,
    ) -> None:
        self._goals = goals
        self._states = states
        self._interpretations = interpretations
        self._provider = provider

    def interpret(self, goal_id: uuid.UUID) -> GoalInterpretation:
        """Ask the wired provider to read the goal against its
        current state, and record the proposal verbatim.

        Raises :class:`NoProviderError` when no LLM is wired,
        :class:`GoalNotFoundError` / :class:`NoCurrentStateError`
        when there is nothing to read, and
        :class:`~backcasting.domain.llm_provider.ProviderCallError`
        when the vendor call fails.
        """
        if self._provider is None:
            raise NoProviderError("no AI provider is configured")
        goal = self._require_goal(goal_id)
        state = self._states.latest_for_goal(goal_id)
        if state is None:
            raise NoCurrentStateError(
                f"no current state for goal {goal_id}"
            )
        response = self._provider.complete(
            build_goal_interpretation_context(goal, state)
        )
        record = record_goal_interpretation(
            goal_id,
            response.content,
            provider=self._provider.name,
            model=response.model,
        )
        self._interpretations.save(record)
        return record

    def list_interpretations(
        self, goal_id: uuid.UUID
    ) -> tuple[GoalInterpretation, ...]:
        """The goal's reading history — every recorded proposal with
        its provenance, earliest first. A re-interpretation is a new
        record; the history keeps them all."""
        self._require_goal(goal_id)
        return tuple(self._interpretations.list_for_goal(goal_id))

    def _require_goal(self, goal_id: uuid.UUID) -> Goal:
        goal = self._goals.get(goal_id)
        if goal is None:
            raise GoalNotFoundError(f"no goal {goal_id}")
        return goal
