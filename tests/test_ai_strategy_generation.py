"""Tests for strategy generation (TASK-096).

The AI half of pipeline step 8: the record with provenance, the
persistence port, the use case wiring context -> provider ->
record, and the seam where the deterministic half (acceptance into
a RUNNING run) takes over.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.strategy_generation import generate_strategies
from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import create_goal
from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCallError,
)
from backcasting.domain.repositories import StrategyGenerationRepository
from backcasting.domain.strategy import StrategyProposal, accept_proposed_strategies
from backcasting.domain.strategy_generation import (
    StrategyGeneration,
    StrategyGenerationError,
    generations_for_goal,
    record_strategy_generation,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
PROPOSAL_TEXT = (
    "1. Conservative build: three easy months, then a 16-week plan.\n"
    "2. Run-walk: intervals from the first week."
)


class FakeProvider(LLMProvider):
    def __init__(self, content=PROPOSAL_TEXT, fail=None):
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
def state(goal):
    return CurrentState(
        state_id=uuid.uuid4(),
        goal_id=goal.goal_id,
        narrative="Couch-bound; 30-minute walks feel long.",
        captured_at=CREATED,
    )


@pytest.fixture
def future(goal):
    return FutureState(
        state_id=uuid.uuid4(),
        goal_id=goal.goal_id,
        description="A marathon finished under five hours.",
        target_date=datetime(2026, 10, 11, tzinfo=timezone.utc),
        created_at=CREATED,
        updated_at=CREATED,
    )


class TestStrategyGenerationRecord:
    def _record(self, **overrides):
        kwargs = dict(
            generation_id=uuid.uuid4(),
            goal_id=uuid.uuid4(),
            proposal=PROPOSAL_TEXT,
            provider="fake",
            model="fake-1",
            created_at=CREATED,
        )
        kwargs.update(overrides)
        return StrategyGeneration(**kwargs)

    def test_shape(self) -> None:
        record = self._record()
        assert record.provider == "fake"
        assert record.model == "fake-1"

    def test_proposal_must_be_non_empty_and_bounded(self) -> None:
        with pytest.raises(StrategyGenerationError, match="proposal"):
            self._record(proposal="   ")
        with pytest.raises(StrategyGenerationError, match="proposal"):
            self._record(proposal=PROPOSAL_TEXT * 2000)

    def test_ids_must_be_uuids(self) -> None:
        with pytest.raises(StrategyGenerationError, match="generation_id"):
            self._record(generation_id="id")  # type: ignore[arg-type]
        with pytest.raises(StrategyGenerationError, match="goal_id"):
            self._record(goal_id="goal")  # type: ignore[arg-type]

    def test_provenance_is_mandatory_and_bounded(self) -> None:
        with pytest.raises(StrategyGenerationError, match="provider"):
            self._record(provider="")
        with pytest.raises(StrategyGenerationError, match="provider"):
            self._record(provider="x" * 101)
        with pytest.raises(StrategyGenerationError, match="model"):
            self._record(model="  ")

    def test_created_at_must_be_utc(self) -> None:
        with pytest.raises(StrategyGenerationError, match="timezone-aware"):
            self._record(created_at=CREATED.replace(tzinfo=None))
        with pytest.raises(StrategyGenerationError, match="must be in UTC"):
            self._record(
                created_at=CREATED.astimezone(timezone(timedelta(hours=5)))
            )

    def test_record_helper_defaults(self) -> None:
        record = record_strategy_generation(
            uuid.uuid4(), PROPOSAL_TEXT, provider="fake", model="fake-1"
        )
        assert isinstance(record.generation_id, uuid.UUID)
        assert record.created_at.tzinfo is timezone.utc


class TestGenerationsForGoal:
    def test_filters_by_goal_in_input_order(self) -> None:
        goal_id, other = uuid.uuid4(), uuid.uuid4()
        generations = tuple(
            record_strategy_generation(
                goal_id if index % 2 == 0 else other,
                f"Strategy batch {index}.",
                provider="fake",
                model="fake-1",
            )
            for index in range(4)
        )
        mine = generations_for_goal(generations, goal_id)
        assert [g.proposal for g in mine] == [
            "Strategy batch 0.", "Strategy batch 2.",
        ]

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(StrategyGenerationError, match="must be a tuple"):
            generations_for_goal([], uuid.uuid4())  # type: ignore[arg-type]
        with pytest.raises(StrategyGenerationError, match="instances"):
            generations_for_goal(("record",), uuid.uuid4())  # type: ignore[arg-type]


class InMemoryStrategyGenerationRepository(StrategyGenerationRepository):
    """The reference fake for the port."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, StrategyGeneration] = {}

    def save(self, generation: StrategyGeneration) -> None:
        self._by_id[generation.generation_id] = generation

    def get(self, generation_id):
        return self._by_id.get(generation_id)

    def list_for_goal(self, goal_id):
        return tuple(
            sorted(
                (g for g in self._by_id.values() if g.goal_id == goal_id),
                key=lambda g: g.created_at,
            )
        )


class TestPort:
    def test_the_reference_fake_honors_the_port_shape(self) -> None:
        repo = InMemoryStrategyGenerationRepository()
        goal_id = uuid.uuid4()
        first = record_strategy_generation(
            goal_id, "First.", provider="fake", model="fake-1",
            created_at=CREATED,
        )
        second = record_strategy_generation(
            goal_id, "Second.", provider="fake", model="fake-1",
            created_at=CREATED + timedelta(hours=1),
        )
        assert repo.get(first.generation_id) is None
        repo.save(first)
        repo.save(second)
        assert repo.get(first.generation_id) is first
        assert [g.proposal for g in repo.list_for_goal(goal_id)] == [
            "First.", "Second.",
        ]


class TestUseCase:
    def test_the_full_arc(self, goal, state, future) -> None:
        provider = FakeProvider()
        generation = generate_strategies(goal, state, future, provider)
        assert generation.goal_id == goal.goal_id
        assert generation.proposal == PROPOSAL_TEXT
        assert generation.provider == "fake"
        assert generation.model == "fake-1"

    def test_the_request_carries_the_three_anchors(
        self, goal, state, future
    ) -> None:
        provider = FakeProvider()
        generate_strategies(goal, state, future, provider)
        (request,) = provider.requests
        assert request.operation == "strategy-generation"
        body = request.messages[1].content
        assert "## Goal" in body
        assert "## Current state" in body
        assert "## Future state" in body
        assert body.count("##") == 3

    def test_vendor_failures_propagate_untouched(
        self, goal, state, future
    ) -> None:
        fault = ProviderCallError("anthropic call failed: 503")
        provider = FakeProvider(fail=fault)
        with pytest.raises(ProviderCallError) as record:
            generate_strategies(goal, state, future, provider)
        assert record.value is fault


class TestTheSeamToTheDeterministicHalf:
    def test_a_generation_feeds_acceptance_by_way_of_proposals(
        self, goal, state, future
    ) -> None:
        """The seam TASK-100 will automate: the recorded proposal,
        read as name/rationale candidates, enters the existing
        deterministic acceptance — here pinned by hand so the two
        halves provably meet."""
        from backcasting.domain.backcasting_run import start_run
        from backcasting.domain.gap import calculate_gap

        provider = FakeProvider()
        generation = generate_strategies(goal, state, future, provider)

        gap = calculate_gap(goal, state, future, calculated_at=CREATED)
        run = start_run(goal, state, future, gap, started_at=CREATED)
        candidates = accept_proposed_strategies(
            run,
            (
                StrategyProposal(
                    name="Conservative build",
                    rationale="Three easy months, then a 16-week plan.",
                ),
                StrategyProposal(name="Run-walk"),
            ),
            at=CREATED,
        )
        assert all(c.run_id == run.run_id for c in candidates)
        assert generation.proposal.startswith("1. Conservative build")
