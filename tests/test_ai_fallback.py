"""Tests for AI fallback (TASK-103).

The graceful-degradation policy: vendor faults and never-validating
proposals fall back to the deterministic path with a recorded
reason; permission denials and programming errors stay loud. And
the fallback is real: the manual path still works afterwards.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.ai_fallback import (
    FALLS_BACK_ON,
    attempt_outcomes,
    attempt_strategies,
    attempt_tasks,
)
from backcasting.application.context_builder import build_strategy_context
from backcasting.application.permission_guard import PermittedProvider
from backcasting.domain.ai_fallback import AIFallbackError, Fallback
from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import Goal, create_goal
from backcasting.domain.gap import calculate_gap
from backcasting.domain.backcasting_run import start_run
from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCallError,
)
from backcasting.domain.outcome import define_outcome
from backcasting.domain.plan import create_plan
from backcasting.domain.proposal_parsing import ProposalParseError
from backcasting.domain.strategy import StrategyProposal, accept_proposed_strategies
from backcasting.domain.task import TaskProposal, accept_proposed_tasks
from backcasting.domain.tool_permissions import (
    ToolPermissionError,
    grant_operations,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
STRATEGY_JSON = '[{"name": "Conservative build-up", "rationale": "Steady"}]'
OUTCOME_JSON = '["Aerobic base built"]'
TASK_JSON = (
    '[{"title": "Weekly long run", "duration_hours": 2, '
    '"outcomes": ["Aerobic base built"]}]'
)


class FakeProvider(LLMProvider):
    def __init__(self, contents=(), fail=None):
        self.contents = list(contents)
        self.fail = fail
        self.calls = 0

    @property
    def name(self) -> str:
        return "fake"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        if not self.contents:
            raise AssertionError("scripted provider ran dry")
        content = self.contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return LLMResponse(content=content, model="fake-1")


@pytest.fixture
def backcast():
    goal = Goal(
        goal_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Run a marathon",
        created_at=CREATED,
        updated_at=CREATED,
    )
    state = CurrentState(
        state_id=uuid.uuid4(),
        goal_id=goal.goal_id,
        narrative="A comfortable 10 km week.",
        captured_at=CREATED,
    )
    future = FutureState(
        state_id=uuid.uuid4(),
        goal_id=goal.goal_id,
        description="A marathon finished under five hours.",
        target_date=datetime(2026, 10, 11, tzinfo=timezone.utc),
        created_at=CREATED,
        updated_at=CREATED,
    )
    return goal, state, future


@pytest.fixture
def plan_and_outcomes():
    goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
    plan = create_plan(goal, 160 * HOUR, created_at=CREATED)
    outcomes = (define_outcome(plan, "Aerobic base built", created_at=CREATED),)
    return goal, plan, outcomes


class TestThePolicy:
    def test_vendor_faults_fall_back(self, backcast) -> None:
        goal, state, future = backcast
        result, fallback = attempt_strategies(
            goal, state, future,
            FakeProvider(fail=ProviderCallError("anthropic: overloaded")),
        )
        assert result is None
        assert fallback is not None
        assert "ProviderCallError" in fallback.reason
        assert "overloaded" in fallback.reason

    def test_never_validating_proposals_fall_back(self, backcast) -> None:
        goal, state, future = backcast
        provider = FakeProvider(["not json", "still not json"])
        result, fallback = attempt_strategies(
            goal, state, future, provider, max_attempts=2
        )
        assert result is None
        assert fallback is not None
        assert "ProposalParseError" in fallback.reason
        assert provider.calls == 2

    def test_permission_denials_stay_loud(self, backcast) -> None:
        goal, state, future = backcast
        guard = PermittedProvider(
            FakeProvider(contents=[STRATEGY_JSON]),
            grant_operations(("explanation",)),
        )
        with pytest.raises(ToolPermissionError):
            attempt_strategies(goal, state, future, guard)

    def test_programming_errors_stay_loud(self, backcast) -> None:
        from backcasting.domain.llm_provider import LLMProviderError

        goal, state, future = backcast
        with pytest.raises(LLMProviderError):
            attempt_strategies(
                goal, state, future,
                FakeProvider(fail=LLMProviderError("bad request shape")),
            )

    def test_the_policy_is_exactly_two_failures(self) -> None:
        assert FALLS_BACK_ON == (ProviderCallError, ProposalParseError)


class TestTheSuccessPath:
    def test_strategies(self, backcast) -> None:
        goal, state, future = backcast
        result, fallback = attempt_strategies(
            goal, state, future, FakeProvider(contents=[STRATEGY_JSON])
        )
        assert fallback is None
        record, proposals = result
        assert record.provider == "fake"
        assert proposals[0].name == "Conservative build-up"

    def test_outcomes(self, backcast) -> None:
        _, _, future = backcast
        result, fallback = attempt_outcomes(
            future, FakeProvider(contents=[OUTCOME_JSON])
        )
        assert fallback is None
        record, titles = result
        assert titles == ("Aerobic base built",)
        assert record.future_state_id == future.state_id

    def test_tasks(self, plan_and_outcomes) -> None:
        _, _, outcomes = plan_and_outcomes
        result, fallback = attempt_tasks(
            outcomes, FakeProvider(contents=[TASK_JSON])
        )
        assert fallback is None
        record, proposals = result
        assert proposals[0].title == "Weekly long run"
        assert record.plan_id == outcomes[0].plan_id


class TestTheFallbackRecord:
    def test_reason_is_validated(self) -> None:
        with pytest.raises(AIFallbackError, match="non-empty"):
            Fallback("  ")
        with pytest.raises(AIFallbackError, match="at most"):
            Fallback("x" * 501)

    def test_the_reason_carries_the_error_class(self, backcast) -> None:
        _, _, future = backcast
        _, fallback = attempt_outcomes(
            future, FakeProvider(fail=ProviderCallError("google: 503"))
        )
        assert fallback.reason.startswith("ProviderCallError: google: 503")


class TestTheDeterministicPathSurvives:
    def test_manual_strategies_after_a_fallback(self, backcast) -> None:
        """The point of the fallback: the AI path gave way, and the
        human path — hand-written proposals through the same
        deterministic rules — still works."""
        goal, state, future = backcast
        result, fallback = attempt_strategies(
            goal, state, future,
            FakeProvider(fail=ProviderCallError("openai: timeout")),
        )
        assert result is None and fallback is not None

        gap = calculate_gap(
            goal, state, future,
            narrative="Endurance is the constraint.", calculated_at=CREATED,
        )
        run = start_run(goal, state, future, gap, started_at=CREATED)
        strategies = accept_proposed_strategies(
            run,
            (StrategyProposal("Conservative build-up", "Written by hand"),),
            at=CREATED,
        )
        assert strategies[0].status.value == "candidate"

    def test_manual_tasks_after_a_fallback(self, plan_and_outcomes) -> None:
        _, plan, outcomes = plan_and_outcomes
        result, fallback = attempt_tasks(
            outcomes, FakeProvider(fail=ProviderCallError("openai: timeout"))
        )
        assert result is None and fallback is not None

        tasks = accept_proposed_tasks(
            plan,
            outcomes,
            (TaskProposal(title="Weekly long run", duration=2 * HOUR),),
            at=CREATED,
        )
        assert tasks[0].title == "Weekly long run"
