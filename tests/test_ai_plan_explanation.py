"""Tests for plan explanation (TASK-099).

docs/09's sixth AI operation: the explanation is the product — the
record with provenance tied to the plan and the snapshot it reads,
the persistence port, and the use case. Unlike the proposal
operations there is no deterministic half to seam-test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.plan_explanation import explain_plan
from backcasting.domain.goal import Goal, create_goal
from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCallError,
)
from backcasting.domain.plan import create_plan
from backcasting.domain.plan_explanation import (
    PlanExplanation,
    PlanExplanationError,
    explanations_for_plan,
    record_plan_explanation,
)
from backcasting.domain.progress import take_progress_snapshot
from backcasting.domain.repositories import PlanExplanationRepository
from backcasting.domain.task import create_task

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
EXPLANATION_TEXT = (
    "You are four hours in with sixteen to go. The long runs are "
    "the backbone — protect the Sunday slot, and the race takes "
    "care of itself."
)


class FakeProvider(LLMProvider):
    def __init__(self, content=EXPLANATION_TEXT, fail=None):
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
def plan_tasks_snapshot():
    goal = Goal(
        goal_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Run a marathon",
        created_at=CREATED,
        updated_at=CREATED,
    )
    plan = create_plan(goal, 20 * HOUR, created_at=CREATED)
    tasks = tuple(
        create_task(plan, title, duration=duration, created_at=CREATED)
        for title, duration in (
            ("Weekly long run", 3 * HOUR),
            ("Tempo session", 1 * HOUR),
            ("Race day", 4 * HOUR),
        )
    )
    snapshot = take_progress_snapshot(plan, tasks, (), at=CREATED)
    return goal, plan, tasks, snapshot


class TestPlanExplanationRecord:
    def _record(self, **overrides):
        kwargs = dict(
            explanation_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),
            snapshot_id=uuid.uuid4(),
            proposal=EXPLANATION_TEXT,
            provider="fake",
            model="fake-1",
            created_at=CREATED,
        )
        kwargs.update(overrides)
        return PlanExplanation(**kwargs)

    def test_shape(self) -> None:
        record = self._record()
        assert record.provider == "fake"
        assert record.model == "fake-1"

    def test_proposal_must_be_non_empty_and_bounded(self) -> None:
        with pytest.raises(PlanExplanationError, match="proposal"):
            self._record(proposal="   ")
        with pytest.raises(PlanExplanationError, match="proposal"):
            self._record(proposal=EXPLANATION_TEXT * 2000)

    def test_ids_must_be_uuids(self) -> None:
        with pytest.raises(PlanExplanationError, match="explanation_id"):
            self._record(explanation_id="id")  # type: ignore[arg-type]
        with pytest.raises(PlanExplanationError, match="plan_id"):
            self._record(plan_id="plan")  # type: ignore[arg-type]
        with pytest.raises(PlanExplanationError, match="snapshot_id"):
            self._record(snapshot_id="snap")  # type: ignore[arg-type]

    def test_provenance_is_mandatory_and_bounded(self) -> None:
        with pytest.raises(PlanExplanationError, match="provider"):
            self._record(provider="")
        with pytest.raises(PlanExplanationError, match="provider"):
            self._record(provider="x" * 101)
        with pytest.raises(PlanExplanationError, match="model"):
            self._record(model="  ")

    def test_created_at_must_be_utc(self) -> None:
        with pytest.raises(PlanExplanationError, match="timezone-aware"):
            self._record(created_at=CREATED.replace(tzinfo=None))
        with pytest.raises(PlanExplanationError, match="must be in UTC"):
            self._record(
                created_at=CREATED.astimezone(
                    timezone(timedelta(hours=5))
                )
            )

    def test_record_helper_defaults(self) -> None:
        record = record_plan_explanation(
            uuid.uuid4(), uuid.uuid4(), EXPLANATION_TEXT,
            provider="fake", model="fake-1",
        )
        assert isinstance(record.explanation_id, uuid.UUID)
        assert record.created_at.tzinfo is timezone.utc


class TestExplanationsForPlan:
    def test_filters_by_plan_in_input_order(self) -> None:
        mine, other = uuid.uuid4(), uuid.uuid4()
        explanations = tuple(
            record_plan_explanation(
                mine if index % 2 == 0 else other,
                uuid.uuid4(),
                f"Explanation {index}.",
                provider="fake",
                model="fake-1",
            )
            for index in range(4)
        )
        assert [
            e.proposal for e in explanations_for_plan(explanations, mine)
        ] == ["Explanation 0.", "Explanation 2."]

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(PlanExplanationError, match="must be a tuple"):
            explanations_for_plan([], uuid.uuid4())  # type: ignore[arg-type]
        with pytest.raises(PlanExplanationError, match="instances"):
            explanations_for_plan(("record",), uuid.uuid4())  # type: ignore[arg-type]


class InMemoryPlanExplanationRepository(PlanExplanationRepository):
    """The reference fake for the port."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, PlanExplanation] = {}

    def save(self, explanation: PlanExplanation) -> None:
        self._by_id[explanation.explanation_id] = explanation

    def get(self, explanation_id):
        return self._by_id.get(explanation_id)

    def list_for_plan(self, plan_id):
        return tuple(
            sorted(
                (
                    e
                    for e in self._by_id.values()
                    if e.plan_id == plan_id
                ),
                key=lambda e: e.created_at,
            )
        )


class TestPort:
    def test_the_reference_fake_honors_the_port_shape(self) -> None:
        repo = InMemoryPlanExplanationRepository()
        plan_id = uuid.uuid4()
        first = record_plan_explanation(
            plan_id, uuid.uuid4(), "First.", provider="fake", model="fake-1",
            created_at=CREATED,
        )
        second = record_plan_explanation(
            plan_id, uuid.uuid4(), "Second.", provider="fake", model="fake-1",
            created_at=CREATED + HOUR,
        )
        assert repo.get(first.explanation_id) is None
        repo.save(first)
        repo.save(second)
        assert repo.get(first.explanation_id) is first
        assert [
            e.proposal for e in repo.list_for_plan(plan_id)
        ] == ["First.", "Second."]


class TestUseCase:
    def test_the_full_arc(self, plan_tasks_snapshot) -> None:
        _, plan, tasks, snapshot = plan_tasks_snapshot
        provider = FakeProvider()
        explanation = explain_plan(plan, tasks, snapshot, provider)
        assert explanation.plan_id == plan.plan_id
        assert explanation.snapshot_id == snapshot.snapshot_id
        assert explanation.proposal == EXPLANATION_TEXT
        assert explanation.provider == "fake"
        assert explanation.model == "fake-1"

    def test_the_request_carries_plan_and_progress(
        self, plan_tasks_snapshot
    ) -> None:
        _, plan, tasks, snapshot = plan_tasks_snapshot
        provider = FakeProvider()
        explain_plan(plan, tasks, snapshot, provider)
        (request,) = provider.requests
        assert request.operation == "explanation"
        body = request.messages[1].content
        assert "## Plan" in body
        assert "## Progress" in body
        assert "Weekly long run" in body
        assert "Tasks completed: 0 of 3" in body

    def test_a_fresh_snapshot_gets_a_fresh_explanation(
        self, plan_tasks_snapshot
    ) -> None:
        """The dual anchor in action: re-reading the plan against a
        new snapshot is a new record, not a revision."""
        _, plan, tasks, _ = plan_tasks_snapshot
        provider = FakeProvider()
        first = explain_plan(
            plan, tasks,
            take_progress_snapshot(plan, tasks, (), at=CREATED),
            provider,
        )
        second = explain_plan(
            plan, tasks,
            take_progress_snapshot(
                plan, tasks, (), at=CREATED + 7 * 24 * HOUR
            ),
            provider,
        )
        assert first.plan_id == second.plan_id
        assert first.snapshot_id != second.snapshot_id
        assert first.explanation_id != second.explanation_id

    def test_vendor_failures_propagate_untouched(
        self, plan_tasks_snapshot
    ) -> None:
        _, plan, tasks, snapshot = plan_tasks_snapshot
        fault = ProviderCallError("openai call failed: timeout")
        provider = FakeProvider(fail=fault)
        with pytest.raises(ProviderCallError) as record:
            explain_plan(plan, tasks, snapshot, provider)
        assert record.value is fault

    def test_snapshot_must_belong_to_the_plan(
        self, plan_tasks_snapshot
    ) -> None:
        _, plan, tasks, _ = plan_tasks_snapshot
        other_goal = create_goal(
            uuid.uuid4(), "Another goal", created_at=CREATED
        )
        other_plan = create_plan(other_goal, 5 * HOUR, created_at=CREATED)
        other_snapshot = take_progress_snapshot(
            other_plan, (), (), at=CREATED
        )
        with pytest.raises(PlanExplanationError, match="belong to this plan"):
            explain_plan(plan, tasks, other_snapshot, FakeProvider())

    def test_rejects_bad_arguments(self, plan_tasks_snapshot) -> None:
        _, plan, tasks, snapshot = plan_tasks_snapshot
        with pytest.raises(PlanExplanationError, match="plan must be a Plan"):
            explain_plan("plan", tasks, snapshot, FakeProvider())  # type: ignore[arg-type]
        with pytest.raises(PlanExplanationError, match="snapshot must be"):
            explain_plan(plan, tasks, "snap", FakeProvider())  # type: ignore[arg-type]
