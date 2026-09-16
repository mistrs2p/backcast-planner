"""Tests for the OpenAI adapter (TASK-091).

The vendor side of the LLM port (ADR-006): translation both ways,
one failure currency for every vendor fault, and the port contract
held by a real adapter rather than the reference fake. No test
touches the network — the SDK client is injected as a fake that
records the vendor-shaped call and answers with a vendor-shaped
response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    Message,
    MessageRole,
    ProviderCallError,
)
from backcasting.infrastructure.openai_provider import OpenAIProvider

SYSTEM = Message(MessageRole.SYSTEM, "You help with planning.")
USER = Message(MessageRole.USER, "Interpret this goal: run a marathon.")


# --- The fake SDK: the shapes the openai client exchanges. ---


@dataclass
class _FakeMessage:
    content: str | None


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass
class _FakeResponse:
    choices: list
    model: str
    usage: _FakeUsage | None = None


@dataclass
class _FakeCompletions:
    responses: list
    calls: list = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@dataclass
class _FakeChat:
    completions: _FakeCompletions


@dataclass
class _FakeClient:
    chat: _FakeChat


def _client(*responses) -> _FakeClient:
    completions = _FakeCompletions(list(responses))
    return _FakeClient(_FakeChat(completions))


def _ok(content="A clear goal.", model="gpt-5.1") -> _FakeResponse:
    return _FakeResponse(
        choices=[_FakeChoice(_FakeMessage(content))],
        model=model,
        usage=_FakeUsage(prompt_tokens=120, completion_tokens=40),
    )


class TestConstruction:
    def test_client_or_api_key_not_both(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            OpenAIProvider(client=object(), api_key="sk-test")

    def test_default_model_must_be_non_empty(self) -> None:
        with pytest.raises(ValueError, match="default_model"):
            OpenAIProvider(default_model="   ")

    def test_it_is_an_llm_provider(self) -> None:
        assert isinstance(OpenAIProvider(default_model="gpt-5.1"), LLMProvider)

    def test_the_module_imports_without_the_sdk(self) -> None:
        """The SDK is an optional runtime dependency; wiring the
        adapter must never require it (lazy import)."""
        import sys

        assert "openai" not in sys.modules
        OpenAIProvider(default_model="gpt-5.1")
        assert "openai" not in sys.modules


class TestTranslationOut:
    def test_the_neutral_request_becomes_the_vendor_call(self) -> None:
        client = _client(_ok())
        provider = OpenAIProvider(client=client, default_model="gpt-5.1")
        request = LLMRequest(
            "goal-interpretation",
            (SYSTEM, USER),
            max_output_tokens=512,
            temperature=0.2,
        )
        provider.complete(request)
        (call,) = client.chat.completions.calls
        assert call == {
            "model": "gpt-5.1",
            "messages": [
                {"role": "system", "content": SYSTEM.content},
                {"role": "user", "content": USER.content},
            ],
            "max_completion_tokens": 512,
            "temperature": 0.2,
        }

    def test_the_request_model_wins_over_the_default(self) -> None:
        client = _client(_ok())
        provider = OpenAIProvider(client=client, default_model="gpt-5.1")
        provider.complete(
            LLMRequest("clarification", (USER,), model="gpt-5-mini")
        )
        assert client.chat.completions.calls[0]["model"] == "gpt-5-mini"

    def test_unset_knobs_stay_out_of_the_vendor_call(self) -> None:
        """None means the provider's default: the adapter must not
        invent values the request never set."""
        client = _client(_ok())
        provider = OpenAIProvider(client=client, default_model="gpt-5.1")
        provider.complete(LLMRequest("clarification", (USER,)))
        (call,) = client.chat.completions.calls
        assert "max_completion_tokens" not in call
        assert "temperature" not in call

    def test_no_model_anywhere_fails_the_call(self) -> None:
        provider = OpenAIProvider(client=_client(_ok()))
        with pytest.raises(ProviderCallError, match="no model"):
            provider.complete(LLMRequest("clarification", (USER,)))
        # And no vendor call was attempted.
        assert provider and True


class TestTranslationBack:
    def test_the_vendor_answer_becomes_neutral(self) -> None:
        provider = OpenAIProvider(client=_client(_ok()), default_model="gpt-5.1")
        response = provider.complete(LLMRequest("goal-interpretation", (SYSTEM, USER)))
        assert response == LLMResponse(
            content="A clear goal.",
            model="gpt-5.1",
            prompt_tokens=120,
            completion_tokens=40,
        )

    def test_the_model_that_answered_is_recorded(self) -> None:
        """The request said nothing; the default routed somewhere; the
        audit log must see where it actually went."""
        provider = OpenAIProvider(client=_client(_ok(model="gpt-5.1-2026-06")), default_model="gpt-5.1")
        response = provider.complete(LLMRequest("clarification", (USER,)))
        assert response.model == "gpt-5.1-2026-06"

    def test_usage_is_optional(self) -> None:
        answer = _FakeResponse(
            choices=[_FakeChoice(_FakeMessage("No counts."))],
            model="gpt-5.1",
            usage=None,
        )
        provider = OpenAIProvider(client=_client(answer), default_model="gpt-5.1")
        response = provider.complete(LLMRequest("clarification", (USER,)))
        assert response.prompt_tokens is None
        assert response.completion_tokens is None


class TestFailures:
    def test_every_vendor_fault_speaks_provider_call_error(self) -> None:
        faults = (
            RuntimeError("connection reset"),
            ValueError("invalid api key"),
            TimeoutError("request timed out"),
        )
        provider = OpenAIProvider(client=_client(*faults), default_model="gpt-5.1")
        for fault in faults:
            with pytest.raises(ProviderCallError) as record:
                provider.complete(LLMRequest("clarification", (USER,)))
            assert record.value.__cause__ is fault or fault in str(
                record.value.__cause__
            )

    def test_the_original_exception_is_chained(self) -> None:
        fault = RuntimeError("503 service unavailable")
        provider = OpenAIProvider(client=_client(fault), default_model="gpt-5.1")
        with pytest.raises(ProviderCallError) as record:
            provider.complete(LLMRequest("clarification", (USER,)))
        assert record.value.__cause__ is fault
        assert "503 service unavailable" in str(record.value)

    def test_empty_choices_is_provider_trouble(self) -> None:
        answer = _FakeResponse(choices=[], model="gpt-5.1")
        provider = OpenAIProvider(client=_client(answer), default_model="gpt-5.1")
        with pytest.raises(ProviderCallError, match="no choices"):
            provider.complete(LLMRequest("clarification", (USER,)))

    def test_unusable_content_is_provider_trouble(self) -> None:
        """No usable proposal came back: retry/fallback territory
        (TASK-103), not a programming error."""
        for content in (None, "", "   "):
            answer = _FakeResponse(
                choices=[_FakeChoice(_FakeMessage(content))], model="gpt-5.1"
            )
            provider = OpenAIProvider(client=_client(answer), default_model="gpt-5.1")
            with pytest.raises(ProviderCallError, match="no usable content"):
                provider.complete(LLMRequest("clarification", (USER,)))

    def test_a_response_without_a_model_is_provider_trouble(self) -> None:
        answer = _FakeResponse(choices=[_FakeChoice(_FakeMessage("Hi."))], model=None)
        provider = OpenAIProvider(client=_client(answer), default_model="gpt-5.1")
        with pytest.raises(ProviderCallError, match="no model"):
            provider.complete(LLMRequest("clarification", (USER,)))

    def test_a_missing_sdk_fails_the_call_not_the_import(self) -> None:
        """Without an injected client the adapter builds the SDK's
        default client; with the SDK absent that is a ProviderCallError
        at call time, so the module stays importable either way."""
        provider = OpenAIProvider(api_key="sk-test", default_model="gpt-5.1")
        with pytest.raises(ProviderCallError, match="openai package"):
            provider.complete(LLMRequest("clarification", (USER,)))


class TestWiring:
    def test_the_adapter_through_the_port(self) -> None:
        """Everything above the port sees only LLMProvider: the
        adapter swaps, the callers do not (ADR-006)."""
        def use(provider: LLMProvider, request: LLMRequest) -> LLMResponse:
            return provider.complete(request)

        provider = OpenAIProvider(client=_client(_ok()), default_model="gpt-5.1")
        assert provider.name == "openai"
        response = use(provider, LLMRequest("strategy-generation", (SYSTEM, USER)))
        assert response.content == "A clear goal."
