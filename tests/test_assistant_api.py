"""Tests for the AI assistant surface (TASK-116) — the AI
Assistant UI's capability.

docs/09's first operation in the product: the assistant reads the
goal against its current state through the provider port, and the
proposal is recorded verbatim with its provenance. The provider
here is a fake speaking the neutral port — no network, no SDK. The
honest failure states are part of the contract: a server assembled
without an LLM says so (503), a goal without a current state has
nothing to read against (404), and a vendor fault surfaces (502) —
there is no deterministic fallback for *reading* a goal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backcasting.application.assistant import (
    AssistantService,
    NoCurrentStateError,
    NoProviderError,
)
from backcasting.application.backcast import BackcastService
from backcasting.application.goals import GoalNotFoundError
from backcasting.domain.goal import create_goal
from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCallError,
)
from backcasting.infrastructure.memory import (
    InMemoryBackcastingRunRepository,
    InMemoryCurrentStateRepository,
    InMemoryFutureStateRepository,
    InMemoryGapRepository,
    InMemoryGoalInterpretationRepository,
    InMemoryGoalRepository,
)

UTC = timezone.utc
TARGET = datetime(2027, 6, 1, tzinfo=UTC)


class FakeProvider(LLMProvider):
    """Answers every request with a fixed proposal, recording them."""

    def __init__(self, content="A first marathon, finished upright."):
        self.content = content
        self.requests: list[LLMRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self.content, model="fake-1")


class FailingProvider(FakeProvider):
    """Raises the port's one failure currency on every call."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        raise ProviderCallError("vendor unavailable")


class Stack:
    """One wired set of repos + services, as create_app assembles
    them (shared goal and current-state repositories)."""

    def __init__(self, provider=...) -> None:
        self.goals = InMemoryGoalRepository()
        self.states = InMemoryCurrentStateRepository()
        self.runs = InMemoryBackcastingRunRepository()
        self.backcast = BackcastService(
            self.goals,
            self.states,
            InMemoryFutureStateRepository(),
            InMemoryGapRepository(),
            self.runs,
        )
        self.interpretations = InMemoryGoalInterpretationRepository()
        if provider is ...:
            provider = FakeProvider()
        self.assistant = AssistantService(
            self.goals, self.states, self.interpretations, provider
        )

    def goal(self):
        goal = create_goal(uuid.uuid4(), "Run a marathon")
        self.goals.save(goal)
        return goal

    def backcast_goal(self, goal):
        return self.backcast.define_backcast(
            goal_id=goal.goal_id,
            current_narrative="Couch potato",
            future_description="Finish a marathon",
            target_date=TARGET,
        )


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backcasting.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def smart_client():
    """A client whose server has an LLM wired (the fake)."""
    from fastapi.testclient import TestClient

    from backcasting.app import create_app

    with TestClient(create_app(llm_provider=FakeProvider())) as test_client:
        yield test_client


def _backcast_goal(client) -> str:
    goal = client.post(
        "/goals",
        json={"user_id": str(uuid.uuid4()), "title": "Run a marathon"},
    ).json()
    response = client.post(
        f"/goals/{goal['goal_id']}/backcast",
        json={
            "current_narrative": "Couch potato",
            "future_description": "Finish a marathon",
            "target_date": "2027-06-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 201, response.text
    return goal["goal_id"]


class TestAssistantService:
    def test_interpretation_recorded_with_provenance(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        record = stack.assistant.interpret(goal.goal_id)
        assert record.goal_id == goal.goal_id
        assert record.provider == "fake"
        assert record.model == "fake-1"
        assert "marathon" in record.proposal.lower()

    def test_context_reads_exactly_goal_and_state(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        provider = stack.assistant._provider
        stack.assistant.interpret(goal.goal_id)
        assert len(provider.requests) == 1
        request = provider.requests[0]
        assert request.operation == "goal-interpretation"
        text = " ".join(message.content for message in request.messages)
        assert goal.title in text
        assert "Couch potato" in text

    def test_history_keeps_every_reading(self) -> None:
        stack = Stack()
        goal = stack.goal()
        stack.backcast_goal(goal)
        first = stack.assistant.interpret(goal.goal_id)
        second = stack.assistant.interpret(goal.goal_id)
        history = stack.assistant.list_interpretations(goal.goal_id)
        # same-tick readings tie-break by id; membership is the
        # service-level contract, strict order is the repo's
        assert set(history) == {first, second}
        assert len(history) == 2

    def test_no_current_state_to_read_against(self) -> None:
        stack = Stack()
        goal = stack.goal()
        with pytest.raises(NoCurrentStateError):
            stack.assistant.interpret(goal.goal_id)

    def test_unknown_goal(self) -> None:
        stack = Stack()
        with pytest.raises(GoalNotFoundError):
            stack.assistant.interpret(uuid.uuid4())

    def test_no_provider_wired(self) -> None:
        stack = Stack(provider=None)
        goal = stack.goal()
        stack.backcast_goal(goal)
        with pytest.raises(NoProviderError):
            stack.assistant.interpret(goal.goal_id)

    def test_vendor_fault_surfaces(self) -> None:
        stack = Stack(provider=FailingProvider())
        goal = stack.goal()
        stack.backcast_goal(goal)
        with pytest.raises(ProviderCallError):
            stack.assistant.interpret(goal.goal_id)
        # a failed call leaves no proposal record — only attempts
        # that produced a proposal are history
        assert stack.assistant.list_interpretations(goal.goal_id) == ()


class TestAssistantRepository:
    def test_list_for_goal_is_reading_history(self) -> None:
        repo = InMemoryGoalInterpretationRepository()
        from backcasting.domain.goal_interpretation import (
            record_goal_interpretation,
        )

        goal_id = uuid.uuid4()
        first = record_goal_interpretation(
            goal_id,
            "first",
            provider="fake",
            model="fake-1",
            created_at=datetime(2026, 9, 16, 9, 0, tzinfo=UTC),
        )
        second = record_goal_interpretation(
            goal_id,
            "second",
            provider="fake",
            model="fake-1",
            created_at=datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
        )
        repo.save(second)
        repo.save(first)
        assert repo.list_for_goal(goal_id) == (first, second)
        assert repo.list_for_goal(uuid.uuid4()) == ()
        assert repo.get(first.interpretation_id) is first
        assert repo.get(uuid.uuid4()) is None


class TestAssistantHTTP:
    def test_interpretation_over_http(self, smart_client) -> None:
        goal_id = _backcast_goal(smart_client)
        response = smart_client.post(
            f"/goals/{goal_id}/assistant/interpretations"
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["goal_id"] == goal_id
        assert body["provider"] == "fake"
        assert body["model"] == "fake-1"

        history = smart_client.get(
            f"/goals/{goal_id}/assistant/interpretations"
        )
        assert history.status_code == 200, history.text
        assert len(history.json()) == 1
        assert history.json()[0]["proposal"] == body["proposal"]

    def test_history_empty_before_any_reading(self, smart_client) -> None:
        goal_id = _backcast_goal(smart_client)
        response = smart_client.get(
            f"/goals/{goal_id}/assistant/interpretations"
        )
        assert response.status_code == 200, response.text
        assert response.json() == []

    def test_no_provider_is_503(self, client) -> None:
        goal_id = _backcast_goal(client)
        response = client.post(
            f"/goals/{goal_id}/assistant/interpretations"
        )
        assert response.status_code == 503, response.text
        assert "no AI provider" in response.json()["detail"]

    def test_no_current_state_is_404(self, smart_client) -> None:
        goal = smart_client.post(
            "/goals",
            json={"user_id": str(uuid.uuid4()), "title": "Run a marathon"},
        ).json()
        response = smart_client.post(
            f"/goals/{goal['goal_id']}/assistant/interpretations"
        )
        assert response.status_code == 404, response.text
        assert "no current state" in response.json()["detail"]

    def test_unknown_goal_is_404(self, smart_client) -> None:
        response = smart_client.post(
            f"/goals/{uuid.uuid4()}/assistant/interpretations"
        )
        assert response.status_code == 404, response.text
        response = smart_client.get(
            f"/goals/{uuid.uuid4()}/assistant/interpretations"
        )
        assert response.status_code == 404, response.text

    def test_vendor_fault_is_502(self) -> None:
        from fastapi.testclient import TestClient

        from backcasting.app import create_app

        with TestClient(
            create_app(llm_provider=FailingProvider())
        ) as failing_client:
            goal_id = _backcast_goal(failing_client)
            response = failing_client.post(
                f"/goals/{goal_id}/assistant/interpretations"
            )
            assert response.status_code == 502, response.text

    def test_contract_paths(self) -> None:
        import json
        from pathlib import Path

        contract = json.loads(
            (
                Path(__file__).resolve().parent.parent
                / "packages"
                / "contracts"
                / "openapi.json"
            ).read_text(encoding="utf-8")
        )
        paths = contract["paths"]
        assert (
            "/goals/{goal_id}/assistant/interpretations" in paths
        )
        operations = paths["/goals/{goal_id}/assistant/interpretations"]
        assert "post" in operations and "get" in operations
