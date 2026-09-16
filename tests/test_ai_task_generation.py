"""Tests for task generation (TASK-098).

The AI half of pipeline step 12: the record with provenance tied to
the plan the generation serves, the persistence port, the use case,
and the seam to the deterministic half (accept_proposed_tasks).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.task_generation import generate_tasks
from backcasting.domain.goal import Goal, create_goal
from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCallError,
)
from backcasting.domain.outcome import define_outcome
from backcasting.domain.plan import create_plan
from backcasting.domain.repositories import TaskGenerationRepository
from backcasting.domain.task import TaskProposal, accept_proposed_tasks
from backcasting.domain.task_generation import (
    TaskGeneration,
    TaskGenerationError,
    generations_for_plan,
    record_task_generation,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
PROPOSAL_TEXT = (
    "1. Weekly long run — serves Aerobic base (90 min).\n"
    "2. Register for the race — serves Race logistics (30 min)."
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
def plan_and_outcomes():
    goal = Goal(
        goal_id=uuid.uuid4(),
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
    return goal, plan, outcomes


class TestTaskGenerationRecord:
    def _record(self, **overrides):
        kwargs = dict(
            generation_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),
            proposal=PROPOSAL_TEXT,
            provider="fake",
            model="fake-1",
            created_at=CREATED,
        )
        kwargs.update(overrides)
        return TaskGeneration(**kwargs)

    def test_shape(self) -> None:
        record = self._record()
        assert record.provider == "fake"
        assert record.model == "fake-1"

    def test_proposal_must_be_non_empty_and_bounded(self) -> None:
        with pytest.raises(TaskGenerationError, match="proposal"):
            self._record(proposal="   ")
        with pytest.raises(TaskGenerationError, match="proposal"):
            self._record(proposal=PROPOSAL_TEXT * 2000)

    def test_ids_must_be_uuids(self) -> None:
        with pytest.raises(TaskGenerationError, match="generation_id"):
            self._record(generation_id="id")  # type: ignore[arg-type]
        with pytest.raises(TaskGenerationError, match="plan_id"):
            self._record(plan_id="plan")  # type: ignore[arg-type]

    def test_provenance_is_mandatory_and_bounded(self) -> None:
        with pytest.raises(TaskGenerationError, match="provider"):
            self._record(provider="")
        with pytest.raises(TaskGenerationError, match="provider"):
            self._record(provider="x" * 101)
        with pytest.raises(TaskGenerationError, match="model"):
            self._record(model="  ")

    def test_created_at_must_be_utc(self) -> None:
        with pytest.raises(TaskGenerationError, match="timezone-aware"):
            self._record(created_at=CREATED.replace(tzinfo=None))
        with pytest.raises(TaskGenerationError, match="must be in UTC"):
            self._record(
                created_at=CREATED.astimezone(
                    timezone(timedelta(hours=5))
                )
            )

    def test_record_helper_defaults(self) -> None:
        record = record_task_generation(
            uuid.uuid4(), PROPOSAL_TEXT, provider="fake", model="fake-1",
        )
        assert isinstance(record.generation_id, uuid.UUID)
        assert record.created_at.tzinfo is timezone.utc


class TestGenerationsForPlan:
    def test_filters_by_plan_in_input_order(self) -> None:
        mine, other = uuid.uuid4(), uuid.uuid4()
        generations = tuple(
            record_task_generation(
                mine if index % 2 == 0 else other,
                f"Generation {index}.",
                provider="fake",
                model="fake-1",
            )
            for index in range(4)
        )
        assert [
            g.proposal for g in generations_for_plan(generations, mine)
        ] == ["Generation 0.", "Generation 2."]

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(TaskGenerationError, match="must be a tuple"):
            generations_for_plan([], uuid.uuid4())  # type: ignore[arg-type]
        with pytest.raises(TaskGenerationError, match="instances"):
            generations_for_plan(("record",), uuid.uuid4())  # type: ignore[arg-type]


class InMemoryTaskGenerationRepository(TaskGenerationRepository):
    """The reference fake for the port."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, TaskGeneration] = {}

    def save(self, generation: TaskGeneration) -> None:
        self._by_id[generation.generation_id] = generation

    def get(self, generation_id):
        return self._by_id.get(generation_id)

    def list_for_plan(self, plan_id):
        return tuple(
            sorted(
                (
                    g
                    for g in self._by_id.values()
                    if g.plan_id == plan_id
                ),
                key=lambda g: g.created_at,
            )
        )


class TestPort:
    def test_the_reference_fake_honors_the_port_shape(self) -> None:
        repo = InMemoryTaskGenerationRepository()
        plan_id = uuid.uuid4()
        first = record_task_generation(
            plan_id, "First.", provider="fake", model="fake-1",
            created_at=CREATED,
        )
        second = record_task_generation(
            plan_id, "Second.", provider="fake", model="fake-1",
            created_at=CREATED + HOUR,
        )
        assert repo.get(first.generation_id) is None
        repo.save(first)
        repo.save(second)
        assert repo.get(first.generation_id) is first
        assert [
            g.proposal for g in repo.list_for_plan(plan_id)
        ] == ["First.", "Second."]


class TestUseCase:
    def test_the_full_arc(self, plan_and_outcomes) -> None:
        _, plan, outcomes = plan_and_outcomes
        provider = FakeProvider()
        generation = generate_tasks(outcomes, provider)
        assert generation.plan_id == plan.plan_id
        assert generation.proposal == PROPOSAL_TEXT
        assert generation.provider == "fake"
        assert generation.model == "fake-1"

    def test_the_request_carries_only_the_outcomes(
        self, plan_and_outcomes
    ) -> None:
        _, _, outcomes = plan_and_outcomes
        provider = FakeProvider()
        generate_tasks(outcomes, provider)
        (request,) = provider.requests
        assert request.operation == "task-generation"
        body = request.messages[1].content
        assert "## Outcomes" in body
        assert body.count("##") == 1
        for outcome in outcomes:
            assert outcome.title in body

    def test_vendor_failures_propagate_untouched(
        self, plan_and_outcomes
    ) -> None:
        _, _, outcomes = plan_and_outcomes
        fault = ProviderCallError("anthropic call failed: overloaded")
        provider = FakeProvider(fail=fault)
        with pytest.raises(ProviderCallError) as record:
            generate_tasks(outcomes, provider)
        assert record.value is fault

    def test_outcomes_must_be_non_empty(self) -> None:
        with pytest.raises(TaskGenerationError, match="at least one outcome"):
            generate_tasks((), FakeProvider())

    def test_outcomes_must_share_one_plan(self, plan_and_outcomes) -> None:
        goal = create_goal(
            uuid.uuid4(), "Another goal", created_at=CREATED
        )
        other_plan = create_plan(goal, 5 * HOUR, created_at=CREATED)
        _, _, outcomes = plan_and_outcomes
        stray = define_outcome(other_plan, "Elsewhere", created_at=CREATED)
        with pytest.raises(TaskGenerationError, match="share one plan"):
            generate_tasks(outcomes + (stray,), FakeProvider())

    def test_rejects_bad_arguments(self, plan_and_outcomes) -> None:
        with pytest.raises(TaskGenerationError, match="must be a tuple"):
            generate_tasks([], FakeProvider())  # type: ignore[arg-type]
        with pytest.raises(TaskGenerationError, match="instances"):
            generate_tasks(("outcome",), FakeProvider())  # type: ignore[arg-type]


class TestTheSeamToTheDeterministicHalf:
    def test_a_generation_feeds_accept_proposed_tasks(
        self, plan_and_outcomes
    ) -> None:
        """The seam TASK-100 will automate: the recorded proposal,
        read as task proposals with outcome-title references, enters
        the deterministic acceptance — pinned by hand so the two
        halves provably meet."""
        _, plan, outcomes = plan_and_outcomes
        provider = FakeProvider()
        generation = generate_tasks(outcomes, provider)

        proposals = (
            TaskProposal(
                title="Weekly long run",
                description="Aerobic base work.",
                duration=90 * timedelta(minutes=1),
                outcome_titles=("Aerobic base",),
            ),
            TaskProposal(
                title="Register for the race",
                outcome_titles=("Race logistics",),
            ),
        )
        tasks = accept_proposed_tasks(
            plan, outcomes, proposals, at=CREATED
        )
        assert all(t.plan_id == plan.plan_id for t in tasks)
        assert tasks[0].outcome_ids == frozenset(
            {outcomes[0].outcome_id}
        )
        assert generation.proposal.startswith("1. Weekly long run")

    def test_the_goal_fixture_matches_the_domain(self) -> None:
        """The Goal fixture above mirrors create_goal's shape."""
        goal = create_goal(
            uuid.uuid4(), "Run a marathon", created_at=CREATED
        )
        assert isinstance(goal, Goal)
