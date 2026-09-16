"""Tests for outcome decomposition (TASK-097).

The AI half of pipeline step 11: the record with provenance tied to
the future state it decomposes, the persistence port, the use case,
and the seam to the deterministic half (define_outcome).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.outcome_decomposition import decompose_outcomes
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import create_goal
from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCallError,
)
from backcasting.domain.outcome import define_outcome
from backcasting.domain.outcome_decomposition import (
    OutcomeDecomposition,
    OutcomeDecompositionError,
    decompositions_for_future,
    record_outcome_decomposition,
)
from backcasting.domain.plan import create_plan
from backcasting.domain.repositories import OutcomeDecompositionRepository

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
PROPOSAL_TEXT = (
    "1. Aerobic base: a 40 km week, comfortably.\n"
    "2. Race logistics: a registered entry and a rehearsed morning."
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
def future():
    goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
    return FutureState(
        state_id=uuid.uuid4(),
        goal_id=goal.goal_id,
        description="A marathon finished under five hours.",
        target_date=datetime(2026, 10, 11, tzinfo=timezone.utc),
        created_at=CREATED,
        updated_at=CREATED,
    )


class TestOutcomeDecompositionRecord:
    def _record(self, **overrides):
        kwargs = dict(
            decomposition_id=uuid.uuid4(),
            goal_id=uuid.uuid4(),
            future_state_id=uuid.uuid4(),
            proposal=PROPOSAL_TEXT,
            provider="fake",
            model="fake-1",
            created_at=CREATED,
        )
        kwargs.update(overrides)
        return OutcomeDecomposition(**kwargs)

    def test_shape(self) -> None:
        record = self._record()
        assert record.provider == "fake"
        assert record.model == "fake-1"

    def test_proposal_must_be_non_empty_and_bounded(self) -> None:
        with pytest.raises(OutcomeDecompositionError, match="proposal"):
            self._record(proposal="   ")
        with pytest.raises(OutcomeDecompositionError, match="proposal"):
            self._record(proposal=PROPOSAL_TEXT * 2000)

    def test_ids_must_be_uuids(self) -> None:
        with pytest.raises(OutcomeDecompositionError, match="decomposition_id"):
            self._record(decomposition_id="id")  # type: ignore[arg-type]
        with pytest.raises(OutcomeDecompositionError, match="goal_id"):
            self._record(goal_id="goal")  # type: ignore[arg-type]
        with pytest.raises(OutcomeDecompositionError, match="future_state_id"):
            self._record(future_state_id="future")  # type: ignore[arg-type]

    def test_provenance_is_mandatory_and_bounded(self) -> None:
        with pytest.raises(OutcomeDecompositionError, match="provider"):
            self._record(provider="")
        with pytest.raises(OutcomeDecompositionError, match="provider"):
            self._record(provider="x" * 101)
        with pytest.raises(OutcomeDecompositionError, match="model"):
            self._record(model="  ")

    def test_created_at_must_be_utc(self) -> None:
        with pytest.raises(OutcomeDecompositionError, match="timezone-aware"):
            self._record(created_at=CREATED.replace(tzinfo=None))
        with pytest.raises(OutcomeDecompositionError, match="must be in UTC"):
            self._record(
                created_at=CREATED.astimezone(timezone(timedelta(hours=5)))
            )

    def test_record_helper_defaults(self) -> None:
        record = record_outcome_decomposition(
            uuid.uuid4(), uuid.uuid4(), PROPOSAL_TEXT,
            provider="fake", model="fake-1",
        )
        assert isinstance(record.decomposition_id, uuid.UUID)
        assert record.created_at.tzinfo is timezone.utc


class TestDecompositionsForFuture:
    def test_filters_by_future_state_in_input_order(self) -> None:
        mine, other = uuid.uuid4(), uuid.uuid4()
        decompositions = tuple(
            record_outcome_decomposition(
                uuid.uuid4(),
                mine if index % 2 == 0 else other,
                f"Decomposition {index}.",
                provider="fake",
                model="fake-1",
            )
            for index in range(4)
        )
        assert [
            d.proposal for d in decompositions_for_future(decompositions, mine)
        ] == ["Decomposition 0.", "Decomposition 2."]

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(OutcomeDecompositionError, match="must be a tuple"):
            decompositions_for_future([], uuid.uuid4())  # type: ignore[arg-type]
        with pytest.raises(OutcomeDecompositionError, match="instances"):
            decompositions_for_future(("record",), uuid.uuid4())  # type: ignore[arg-type]


class InMemoryOutcomeDecompositionRepository(OutcomeDecompositionRepository):
    """The reference fake for the port."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, OutcomeDecomposition] = {}

    def save(self, decomposition: OutcomeDecomposition) -> None:
        self._by_id[decomposition.decomposition_id] = decomposition

    def get(self, decomposition_id):
        return self._by_id.get(decomposition_id)

    def list_for_future_state(self, future_state_id):
        return tuple(
            sorted(
                (
                    d
                    for d in self._by_id.values()
                    if d.future_state_id == future_state_id
                ),
                key=lambda d: d.created_at,
            )
        )


class TestPort:
    def test_the_reference_fake_honors_the_port_shape(self) -> None:
        repo = InMemoryOutcomeDecompositionRepository()
        future_id = uuid.uuid4()
        first = record_outcome_decomposition(
            uuid.uuid4(), future_id, "First.", provider="fake", model="fake-1",
            created_at=CREATED,
        )
        second = record_outcome_decomposition(
            uuid.uuid4(), future_id, "Second.", provider="fake", model="fake-1",
            created_at=CREATED + HOUR,
        )
        assert repo.get(first.decomposition_id) is None
        repo.save(first)
        repo.save(second)
        assert repo.get(first.decomposition_id) is first
        assert [
            d.proposal for d in repo.list_for_future_state(future_id)
        ] == ["First.", "Second."]


class TestUseCase:
    def test_the_full_arc(self, future) -> None:
        provider = FakeProvider()
        decomposition = decompose_outcomes(future, provider)
        assert decomposition.goal_id == future.goal_id
        assert decomposition.future_state_id == future.state_id
        assert decomposition.proposal == PROPOSAL_TEXT
        assert decomposition.provider == "fake"
        assert decomposition.model == "fake-1"

    def test_the_request_carries_only_the_future(self, future) -> None:
        provider = FakeProvider()
        decompose_outcomes(future, provider)
        (request,) = provider.requests
        assert request.operation == "outcome-decomposition"
        body = request.messages[1].content
        assert "## Future state" in body
        assert body.count("##") == 1

    def test_vendor_failures_propagate_untouched(self, future) -> None:
        fault = ProviderCallError("google call failed: 503")
        provider = FakeProvider(fail=fault)
        with pytest.raises(ProviderCallError) as record:
            decompose_outcomes(future, provider)
        assert record.value is fault


class TestTheSeamToTheDeterministicHalf:
    def test_a_decomposition_feeds_define_outcome(self, future) -> None:
        """The seam TASK-100 will automate: the recorded proposal,
        read as outcome titles, enters the deterministic definition —
        pinned by hand so the two halves provably meet."""
        from backcasting.domain.goal import Goal

        provider = FakeProvider()
        decomposition = decompose_outcomes(future, provider)

        goal = Goal(
            goal_id=future.goal_id,
            user_id=uuid.uuid4(),
            title="Run a marathon",
            created_at=CREATED,
            updated_at=CREATED,
        )
        plan = create_plan(goal, 10 * HOUR, created_at=CREATED)
        outcomes = tuple(
            define_outcome(plan, title, created_at=CREATED)
            for title in ("Aerobic base", "Race logistics")
        )
        assert all(o.plan_id == plan.plan_id for o in outcomes)
        assert decomposition.proposal.startswith("1. Aerobic base")
