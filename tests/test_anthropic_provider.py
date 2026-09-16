"""Tests for the Anthropic adapter (TASK-092).

The second vendor behind the LLM port: the same contract as the
OpenAI adapter over a different API shape — system prompts hoisted
to a top-level parameter, a required output bound resolved from the
adapter's default, content blocks joined back into one proposal.
No test touches the network; the SDK client is a recording fake.
"""

from __future__ import annotations

import sys
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
from backcasting.infrastructure.anthropic_provider import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    AnthropicProvider,
)

SYSTEM = Message(MessageRole.SYSTEM, "You help with planning.")
SECOND_SYSTEM = Message(MessageRole.SYSTEM, "Answer concisely.")
USER = Message(MessageRole.USER, "Interpret this goal: run a marathon.")
ASSISTANT = Message(MessageRole.ASSISTANT, "Which marathon?")


# --- The fake SDK: the shapes the anthropic client exchanges. ---


@dataclass
class _FakeTextBlock:
    text: str | None


@dataclass
class _FakeUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class _FakeResponse:
    content: list
    model: str
    usage: _FakeUsage | None = None


@dataclass
class _FakeMessages:
    responses: list
    calls: list = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@dataclass
class _FakeClient:
    messages: _FakeMessages


def _client(*responses) -> _FakeClient:
    return _FakeClient(_FakeMessages(list(responses)))


def _ok(text="A clear goal.", model="claude-sonnet-5") -> _FakeResponse:
    return _FakeResponse(
        content=[_FakeTextBlock(text)],
        model=model,
        usage=_FakeUsage(input_tokens=100, output_tokens=30),
    )


class TestConstruction:
    def test_client_or_api_key_not_both(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            AnthropicProvider(client=object(), api_key="sk-ant-test")

    def test_defaults_are_validated(self) -> None:
        with pytest.raises(ValueError, match="default_model"):
            AnthropicProvider(default_model="   ")
        for bad in (0, -1, True, "512", 512.0):
            with pytest.raises(ValueError, match="default_max_output_tokens"):
                AnthropicProvider(default_max_output_tokens=bad)

    def test_it_is_an_llm_provider(self) -> None:
        assert isinstance(
            AnthropicProvider(default_model="claude-sonnet-5"), LLMProvider
        )

    def test_the_module_imports_without_the_sdk(self) -> None:
        assert "anthropic" not in sys.modules
        AnthropicProvider(default_model="claude-sonnet-5")
        assert "anthropic" not in sys.modules


class TestTranslationOut:
    def test_the_neutral_request_becomes_the_vendor_call(self) -> None:
        client = _client(_ok())
        provider = AnthropicProvider(
            client=client, default_model="claude-sonnet-5"
        )
        request = LLMRequest(
            "goal-interpretation",
            (SYSTEM, USER),
            max_output_tokens=512,
            temperature=0.2,
        )
        provider.complete(request)
        (call,) = client.messages.calls
        assert call == {
            "model": "claude-sonnet-5",
            "messages": [{"role": "user", "content": USER.content}],
            "max_tokens": 512,
            "system": SYSTEM.content,
            "temperature": 0.2,
        }

    def test_system_turns_are_hoisted_not_inlined(self) -> None:
        """The vendor's shape: system text is a top-level parameter,
        and only user/assistant turns form the message list."""
        client = _client(_ok())
        provider = AnthropicProvider(
            client=client, default_model="claude-sonnet-5"
        )
        provider.complete(
            LLMRequest("clarification", (SYSTEM, USER, ASSISTANT, USER))
        )
        (call,) = client.messages.calls
        assert call["system"] == SYSTEM.content
        assert [m["role"] for m in call["messages"]] == [
            "user", "assistant", "user",
        ]

    def test_multiple_system_turns_are_joined(self) -> None:
        client = _client(_ok())
        provider = AnthropicProvider(
            client=client, default_model="claude-sonnet-5"
        )
        provider.complete(
            LLMRequest("clarification", (SYSTEM, SECOND_SYSTEM, USER))
        )
        (call,) = client.messages.calls
        assert call["system"] == f"{SYSTEM.content}\n\n{SECOND_SYSTEM.content}"

    def test_no_system_turn_means_no_system_parameter(self) -> None:
        client = _client(_ok())
        provider = AnthropicProvider(
            client=client, default_model="claude-sonnet-5"
        )
        provider.complete(LLMRequest("clarification", (USER,)))
        (call,) = client.messages.calls
        assert "system" not in call

    def test_the_request_model_wins_over_the_default(self) -> None:
        client = _client(_ok())
        provider = AnthropicProvider(
            client=client, default_model="claude-sonnet-5"
        )
        provider.complete(
            LLMRequest("clarification", (USER,), model="claude-haiku-4-5")
        )
        assert client.messages.calls[0]["model"] == "claude-haiku-4-5"

    def test_an_unset_output_bound_uses_the_adapter_default(self) -> None:
        """The vendor requires max_tokens on every call; the neutral
        None resolves to the adapter's default, not to a missing
        parameter the vendor would reject."""
        client = _client(_ok())
        provider = AnthropicProvider(
            client=client, default_model="claude-sonnet-5"
        )
        provider.complete(LLMRequest("clarification", (USER,)))
        assert (
            client.messages.calls[0]["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
        )

    def test_the_default_output_bound_is_overridable(self) -> None:
        client = _client(_ok())
        provider = AnthropicProvider(
            client=client,
            default_model="claude-sonnet-5",
            default_max_output_tokens=2048,
        )
        provider.complete(LLMRequest("clarification", (USER,)))
        assert client.messages.calls[0]["max_tokens"] == 2048

    def test_unset_temperature_stays_out_of_the_call(self) -> None:
        client = _client(_ok())
        provider = AnthropicProvider(
            client=client, default_model="claude-sonnet-5"
        )
        provider.complete(LLMRequest("clarification", (USER,)))
        assert "temperature" not in client.messages.calls[0]

    def test_no_model_anywhere_fails_the_call(self) -> None:
        provider = AnthropicProvider(client=_client(_ok()))
        with pytest.raises(ProviderCallError, match="no model"):
            provider.complete(LLMRequest("clarification", (USER,)))


class TestTranslationBack:
    def test_the_vendor_answer_becomes_neutral(self) -> None:
        provider = AnthropicProvider(
            client=_client(_ok()), default_model="claude-sonnet-5"
        )
        response = provider.complete(LLMRequest("goal-interpretation", (SYSTEM, USER)))
        assert response == LLMResponse(
            content="A clear goal.",
            model="claude-sonnet-5",
            prompt_tokens=100,
            completion_tokens=30,
        )

    def test_multiple_text_blocks_are_joined(self) -> None:
        answer = _FakeResponse(
            content=[_FakeTextBlock("First part."), _FakeTextBlock("Second part.")],
            model="claude-sonnet-5",
        )
        provider = AnthropicProvider(
            client=_client(answer), default_model="claude-sonnet-5"
        )
        response = provider.complete(LLMRequest("clarification", (USER,)))
        assert response.content == "First part.\n\nSecond part."

    def test_non_text_blocks_are_skipped(self) -> None:
        answer = _FakeResponse(
            content=[_FakeTextBlock(None), _FakeTextBlock("The text.")],
            model="claude-sonnet-5",
        )
        provider = AnthropicProvider(
            client=_client(answer), default_model="claude-sonnet-5"
        )
        assert provider.complete(LLMRequest("clarification", (USER,))).content == (
            "The text."
        )

    def test_usage_is_optional(self) -> None:
        answer = _FakeResponse(
            content=[_FakeTextBlock("No counts.")], model="claude-sonnet-5"
        )
        provider = AnthropicProvider(
            client=_client(answer), default_model="claude-sonnet-5"
        )
        response = provider.complete(LLMRequest("clarification", (USER,)))
        assert response.prompt_tokens is None
        assert response.completion_tokens is None


class TestFailures:
    def test_every_vendor_fault_speaks_provider_call_error(self) -> None:
        faults = (
            RuntimeError("connection reset"),
            ValueError("invalid x-api-key"),
            TimeoutError("request timed out"),
        )
        provider = AnthropicProvider(
            client=_client(*faults), default_model="claude-sonnet-5"
        )
        for fault in faults:
            with pytest.raises(ProviderCallError) as record:
                provider.complete(LLMRequest("clarification", (USER,)))
            assert record.value.__cause__ is fault

    def test_no_text_blocks_is_provider_trouble(self) -> None:
        for blocks in ([], [_FakeTextBlock(None)], [_FakeTextBlock("   ")]):
            answer = _FakeResponse(content=blocks, model="claude-sonnet-5")
            provider = AnthropicProvider(
                client=_client(answer), default_model="claude-sonnet-5"
            )
            with pytest.raises(ProviderCallError, match="no usable content"):
                provider.complete(LLMRequest("clarification", (USER,)))

    def test_a_response_without_a_model_is_provider_trouble(self) -> None:
        answer = _FakeResponse(
            content=[_FakeTextBlock("Hi.")], model=None
        )
        provider = AnthropicProvider(
            client=_client(answer), default_model="claude-sonnet-5"
        )
        with pytest.raises(ProviderCallError, match="no model"):
            provider.complete(LLMRequest("clarification", (USER,)))

    def test_a_missing_sdk_fails_the_call_not_the_import(self) -> None:
        provider = AnthropicProvider(
            api_key="sk-ant-test", default_model="claude-sonnet-5"
        )
        with pytest.raises(ProviderCallError, match="anthropic package"):
            provider.complete(LLMRequest("clarification", (USER,)))


class TestWiring:
    def test_the_adapter_through_the_port(self) -> None:
        """Two vendors, one interface: the caller cannot tell them
        apart except by name (ADR-006)."""
        from backcasting.infrastructure.openai_provider import OpenAIProvider

        def use(provider: LLMProvider, request: LLMRequest) -> LLMResponse:
            return provider.complete(request)

        anthropic = AnthropicProvider(
            client=_client(_ok()), default_model="claude-sonnet-5"
        )
        openai = OpenAIProvider(
            client=_build_openai_fake(), default_model="gpt-5.1"
        )
        request = LLMRequest("strategy-generation", (SYSTEM, USER))
        assert use(anthropic, request).content == "A clear goal."
        assert use(openai, request).content == "A clear goal."
        assert {anthropic.name, openai.name} == {"anthropic", "openai"}

    def test_an_out_of_vendor_range_temperature_surfaces_not_clamps(self) -> None:
        """Anthropic accepts 0–1, the port allows up to 2: the adapter
        passes the value on and the vendor's rejection arrives as
        ProviderCallError — never a silently clamped proposal."""
        client = _client(ValueError("temperature must be between 0 and 1"))
        provider = AnthropicProvider(
            client=client, default_model="claude-sonnet-5"
        )
        with pytest.raises(ProviderCallError, match="between 0 and 1"):
            provider.complete(
                LLMRequest("clarification", (USER,), temperature=1.5)
            )


def _build_openai_fake() -> Any:
    """A minimal OpenAI-shaped fake for the side-by-side wiring."""
    class _Completions:
        def create(self, **kwargs):
            class _Message:
                content = "A clear goal."

            class _Choice:
                message = _Message()

            class _Response:
                choices = [_Choice()]
                model = "gpt-5.1"

            return _Response()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    return _Client()
