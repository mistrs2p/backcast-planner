"""Tests for goal interpretation (TASK-095).

The first AI operation end to end: domain record with provenance,
persistence port, and the use case wiring context builder -> provider
-> record. The provider is a fake speaking the neutral port — no
network, no SDK.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.goal_interpretation import interpret_goal
from backcasting.domain.current_state import CurrentState
from backcasting.domain.goal import create_goal
from backcasting.domain.goal_interpretation import (
    GoalInterpretation,
    GoalInterpretationError,
    interpretations_for_goal,
    record_goal_interpretation,
)
from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCallError,
)
from backcasting.domain.repositories import GoalInterpretationRepository

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeProvider(LLMProvider):
    """Answers every request with a fixed proposal, recording them."""

    def __init__(self, content="The goal is a first marathon.", fail=None):
        self.content = content
        self.fail = fail
        self.requests: list[LLMRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.fail is not None:
            raise self.fail
        return LLMResponse(content=self.content, model="fake-1")


@pytest.fixture
def goal():
    return create_goal(
        uuid.uuid4(), "Run a marathon", description="Finish upright.",
        created_at=CREATED,
    )


@pytest.fixture
def state():
    return CurrentState(
        state_id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        narrative="Couch-bound; 30-minute walks feel long.",
        captured_at=CREATED,
    )


class TestGoalInterpretationRecord:
    def _record(self, **overrides):
        kwargs = dict(
            interpretation_id=uuid.uuid4(),
            goal_id=uuid.uuid4(),
            proposal="A first marathon, finished upright.",
            provider="fake",
            model="fake-1",
            created_at=CREATED,
        )
        kwargs.update(overrides)
        return GoalInterpretation(**kwargs)

    def test_shape(self) -> None:
        record = self._record()
        assert record.provider == "fake"
        assert record.model == "fake-1"
        assert record.created_at == CREATED

    def test_proposal_must_be_non_empty_and_bounded(self) -> None:
        with pytest.raises(GoalInterpretationError, match="proposal"):
            self._record(proposal="   ")
        with pytest.raises(GoalInterpretationError, match="proposal"):
            self._record(proposal=42)  # type: ignore[arg-type]
        with pytest.raises(GoalInterpretationError, match="proposal"):
            self._record(proposal="x" * 20_001)

    def test_ids_must_be_uuids(self) -> None:
        with pytest.raises(GoalInterpretationError, match="interpretation_id"):
            self._record(interpretation_id="id")  # type: ignore[arg-type]
        with pytest.raises(GoalInterpretationError, match="goal_id"):
            self._record(goal_id="goal")  # type: ignore[arg-type]

    def test_provenance_is_mandatory(self) -> None:
        with pytest.raises(GoalInterpretationError, match="provider"):
            self._record(provider="")
        with pytest.raises(GoalInterpretationError, match="provider"):
            self._record(provider="x" * 101)
        with pytest.raises(GoalInterpretationError, match="model"):
            self._record(model="  ")

    def test_created_at_must_be_utc(self) -> None:
        with pytest.raises(GoalInterpretationError, match="timezone-aware"):
            self._record(created_at=CREATED.replace(tzinfo=None))
        from datetime import timedelta

        with pytest.raises(GoalInterpretationError, match="must be in UTC"):
            self._record(
                created_at=CREATED.astimezone(timezone(timedelta(hours=5)))
            )

    def test_record_helper_defaults(self) -> None:
        record = record_goal_interpretation(
            uuid.uuid4(), "A proposal.", provider="fake", model="fake-1"
        )
        assert isinstance(record.interpretation_id, uuid.UUID)
        assert record.created_at.tzinfo is timezone.utc


class TestInterpretationsForGoal:
    def test_filters_by_goal_in_input_order(self) -> None:
        goal_id, other = uuid.uuid4(), uuid.uuid4()
        records = tuple(
            record_goal_interpretation(
                goal_id if index % 2 == 0 else other,
                f"Proposal {index}.",
                provider="fake",
                model="fake-1",
            )
            for index in range(4)
        )
        mine = interpretations_for_goal(records, goal_id)
        assert [r.proposal for r in mine] == ["Proposal 0.", "Proposal 2."]

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(GoalInterpretationError, match="must be a tuple"):
            interpretations_for_goal([], uuid.uuid4())  # type: ignore[arg-type]
        with pytest.raises(GoalInterpretationError, match="instances"):
            interpretations_for_goal(("record",), uuid.uuid4())  # type: ignore[arg-type]
        with pytest.raises(GoalInterpretationError, match="goal_id must be"):
            interpretations_for_goal((), "goal")  # type: ignore[arg-type]


class InMemoryGoalInterpretationRepository(GoalInterpretationRepository):
    """The reference fake for the port."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, GoalInterpretation] = {}

    def save(self, interpretation: GoalInterpretation) -> None:
        self._by_id[interpretation.interpretation_id] = interpretation

    def get(self, interpretation_id):
        return self._by_id.get(interpretation_id)

    def list_for_goal(self, goal_id):
        return tuple(
            sorted(
                (r for r in self._by_id.values() if r.goal_id == goal_id),
                key=lambda r: r.created_at,
            )
        )


class TestPort:
    def test_the_reference_fake_honors_the_port_shape(self) -> None:
        repo = InMemoryGoalInterpretationRepository()
        goal_id = uuid.uuid4()
        first = record_goal_interpretation(
            goal_id, "First.", provider="fake", model="fake-1",
            created_at=CREATED,
        )
        second = record_goal_interpretation(
            goal_id, "Second.", provider="fake", model="fake-1",
            created_at=CREATED + timedelta(hours=1),
        )
        assert repo.get(first.interpretation_id) is None
        repo.save(first)
        repo.save(second)
        assert repo.get(first.interpretation_id) is first
        assert [r.proposal for r in repo.list_for_goal(goal_id)] == [
            "First.", "Second.",
        ]
        # Save is insert-or-replace: the same id again replaces.
        replaced = record_goal_interpretation(
            goal_id, "First, revised.", provider="fake", model="fake-1",
            created_at=CREATED, interpretation_id=first.interpretation_id,
        )
        repo.save(replaced)
        assert repo.get(first.interpretation_id).proposal == "First, revised."


class TestUseCase:
    def test_the_full_arc(self, goal, state) -> None:
        provider = FakeProvider()
        interpretation = interpret_goal(goal, state, provider)
        assert interpretation.goal_id == goal.goal_id
        assert interpretation.proposal == "The goal is a first marathon."
        assert interpretation.provider == "fake"
        assert interpretation.model == "fake-1"

    def test_the_request_carries_exactly_the_operation_context(
        self, goal, state
    ) -> None:
        """Goal and current state, nothing else — the builder's
        signature guarantees it; this pins that the use case uses
        the builder."""
        provider = FakeProvider()
        interpret_goal(goal, state, provider)
        (request,) = provider.requests
        assert request.operation == "goal-interpretation"
        body = request.messages[1].content
        assert "## Goal" in body
        assert "Run a marathon" in body
        assert "## Current state" in body
        assert body.count("##") == 2

    def test_the_recorded_model_is_the_one_that_answered(
        self, goal, state
    ) -> None:
        provider = FakeProvider()
        provider.content = "Another proposal."
        interpretation = interpret_goal(goal, state, provider)
        assert interpretation.model == "fake-1"

    def test_vendor_failures_propagate_untouched(self, goal, state) -> None:
        """One currency: the use case neither wraps nor swallows
        ProviderCallError — the fallback logic (TASK-103) will catch
        exactly this."""
        fault = ProviderCallError("openai call failed: 503")
        provider = FakeProvider(fail=fault)
        with pytest.raises(ProviderCallError) as record:
            interpret_goal(goal, state, provider)
        assert record.value is fault

    def test_persistence_is_the_callers_wiring(self, goal, state) -> None:
        provider = FakeProvider()
        repo = InMemoryGoalInterpretationRepository()
        interpretation = interpret_goal(goal, state, provider)
        repo.save(interpretation)
        assert repo.list_for_goal(goal.goal_id) == (interpretation,)
