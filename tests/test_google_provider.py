"""Tests for the Google adapter (TASK-093).

The third vendor behind the LLM port: assistant turns renamed to the
vendor's "model" role, the system prompt riding in the config object,
a response whose ``text`` property raises when nothing came back.
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
from backcasting.infrastructure.google_provider import GoogleProvider

SYSTEM = Message(MessageRole.SYSTEM, "You help with planning.")
SECOND_SYSTEM = Message(MessageRole.SYSTEM, "Answer concisely.")
USER = Message(MessageRole.USER, "Interpret this goal: run a marathon.")
ASSISTANT = Message(MessageRole.ASSISTANT, "Which marathon?")


# --- The fake SDK: the shapes the google-genai client exchanges. ---


@dataclass
class _FakeUsage:
    prompt_token_count: int | None = None
    candidates_token_count: int | None = None


@dataclass
class _FakeResponse:
    text_or_fault: Any
    model_version: str
    usage_metadata: _FakeUsage | None = None

    @property
    def text(self) -> str:
        if isinstance(self.text_or_fault, Exception):
            raise self.text_or_fault
        return self.text_or_fault


@dataclass
class _FakeGenerateContent:
    responses: list
    calls: list = field(default_factory=list)

    def __call__(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@dataclass
class _FakeModels:
    generate_content: _FakeGenerateContent


@dataclass
class _FakeClient:
    models: _FakeModels


def _client(*responses) -> _FakeClient:
    return _FakeClient(_FakeModels(_FakeGenerateContent(list(responses))))


def _ok(text="A clear goal.", model="gemini-3-flash") -> _FakeResponse:
    return _FakeResponse(
        text_or_fault=text,
        model_version=model,
        usage_metadata=_FakeUsage(prompt_token_count=90, candidates_token_count=25),
    )


class TestConstruction:
    def test_client_or_api_key_not_both(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            GoogleProvider(client=object(), api_key="gcp-test")

    def test_default_model_must_be_non_empty(self) -> None:
        with pytest.raises(ValueError, match="default_model"):
            GoogleProvider(default_model="   ")

    def test_it_is_an_llm_provider(self) -> None:
        assert isinstance(GoogleProvider(default_model="gemini-3-flash"), LLMProvider)

    def test_the_module_imports_without_the_sdk(self) -> None:
        assert "google" not in sys.modules
        GoogleProvider(default_model="gemini-3-flash")
        assert "google" not in sys.modules


class TestTranslationOut:
    def test_the_neutral_request_becomes_the_vendor_call(self) -> None:
        client = _client(_ok())
        provider = GoogleProvider(client=client, default_model="gemini-3-flash")
        request = LLMRequest(
            "goal-interpretation",
            (SYSTEM, USER),
            max_output_tokens=512,
            temperature=0.2,
        )
        provider.complete(request)
        (call,) = client.models.generate_content.calls
        assert call == {
            "model": "gemini-3-flash",
            "contents": [
                {"role": "user", "parts": [{"text": USER.content}]},
            ],
            "config": {
                "system_instruction": SYSTEM.content,
                "max_output_tokens": 512,
                "temperature": 0.2,
            },
        }

    def test_assistant_turns_speak_the_vendor_role(self) -> None:
        """The vendor says "model" where the port says "assistant";
        the rename is the adapter's, invisible above the port."""
        client = _client(_ok())
        provider = GoogleProvider(client=client, default_model="gemini-3-flash")
        provider.complete(
            LLMRequest("clarification", (SYSTEM, USER, ASSISTANT, USER))
        )
        (call,) = client.models.generate_content.calls
        assert [c["role"] for c in call["contents"]] == [
            "user", "model", "user",
        ]

    def test_multiple_system_turns_are_joined_into_the_instruction(self) -> None:
        client = _client(_ok())
        provider = GoogleProvider(client=client, default_model="gemini-3-flash")
        provider.complete(
            LLMRequest("clarification", (SYSTEM, SECOND_SYSTEM, USER))
        )
        (call,) = client.models.generate_content.calls
        assert call["config"]["system_instruction"] == (
            f"{SYSTEM.content}\n\n{SECOND_SYSTEM.content}"
        )
        assert len(call["contents"]) == 1  # only the user turn

    def test_no_system_turn_means_no_instruction(self) -> None:
        client = _client(_ok())
        provider = GoogleProvider(client=client, default_model="gemini-3-flash")
        provider.complete(LLMRequest("clarification", (USER,)))
        (call,) = client.models.generate_content.calls
        assert "system_instruction" not in call["config"]

    def test_unset_knobs_stay_out_of_the_config(self) -> None:
        """Gemini imposes no required output bound (unlike
        Anthropic): an unset bound is simply absent, and the vendor's
        own default applies, exactly as the port promises."""
        client = _client(_ok())
        provider = GoogleProvider(client=client, default_model="gemini-3-flash")
        provider.complete(LLMRequest("clarification", (USER,)))
        (call,) = client.models.generate_content.calls
        assert call["config"] == {}

    def test_the_request_model_wins_over_the_default(self) -> None:
        client = _client(_ok())
        provider = GoogleProvider(client=client, default_model="gemini-3-flash")
        provider.complete(
            LLMRequest("clarification", (USER,), model="gemini-3-pro")
        )
        assert client.models.generate_content.calls[0]["model"] == "gemini-3-pro"

    def test_a_request_of_only_system_turns_fails_the_call(self) -> None:
        provider = GoogleProvider(client=_client(_ok()), default_model="gemini-3-flash")
        with pytest.raises(ProviderCallError, match="only system messages"):
            provider.complete(LLMRequest("clarification", (SYSTEM,)))

    def test_no_model_anywhere_fails_the_call(self) -> None:
        provider = GoogleProvider(client=_client(_ok()))
        with pytest.raises(ProviderCallError, match="no model"):
            provider.complete(LLMRequest("clarification", (USER,)))


class TestTranslationBack:
    def test_the_vendor_answer_becomes_neutral(self) -> None:
        provider = GoogleProvider(client=_client(_ok()), default_model="gemini-3-flash")
        response = provider.complete(
            LLMRequest("goal-interpretation", (SYSTEM, USER))
        )
        assert response == LLMResponse(
            content="A clear goal.",
            model="gemini-3-flash",
            prompt_tokens=90,
            completion_tokens=25,
        )

    def test_the_model_that_answered_is_recorded(self) -> None:
        answer = _ok(model="gemini-3-flash-2026-06")
        provider = GoogleProvider(client=_client(answer), default_model="gemini-3-flash")
        response = provider.complete(LLMRequest("clarification", (USER,)))
        assert response.model == "gemini-3-flash-2026-06"

    def test_usage_is_optional(self) -> None:
        answer = _FakeResponse(
            text_or_fault="No counts.", model_version="gemini-3-flash"
        )
        provider = GoogleProvider(client=_client(answer), default_model="gemini-3-flash")
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
        provider = GoogleProvider(
            client=_client(*faults), default_model="gemini-3-flash"
        )
        for fault in faults:
            with pytest.raises(ProviderCallError) as record:
                provider.complete(LLMRequest("clarification", (USER,)))
            assert record.value.__cause__ is fault

    def test_a_raising_text_property_is_provider_trouble(self) -> None:
        """The vendor's ``text`` property raises on a safety refusal
        or empty candidates; that must arrive as the one failure
        currency, never as the vendor's own exception."""
        provider = GoogleProvider(
            client=_client(_FakeResponse(
                text_or_fault=ValueError("No candidates returned"),
                model_version="gemini-3-flash",
            )),
            default_model="gemini-3-flash",
        )
        with pytest.raises(ProviderCallError, match="no usable content"):
            provider.complete(LLMRequest("clarification", (USER,)))

    def test_blank_text_is_provider_trouble(self) -> None:
        for text in (None, "", "   "):
            answer = _FakeResponse(text_or_fault=text, model_version="gemini-3-flash")
            provider = GoogleProvider(
                client=_client(answer), default_model="gemini-3-flash"
            )
            with pytest.raises(ProviderCallError, match="no usable content"):
                provider.complete(LLMRequest("clarification", (USER,)))

    def test_a_response_without_a_model_is_provider_trouble(self) -> None:
        answer = _FakeResponse(text_or_fault="Hi.", model_version=None)
        provider = GoogleProvider(client=_client(answer), default_model="gemini-3-flash")
        with pytest.raises(ProviderCallError, match="no model"):
            provider.complete(LLMRequest("clarification", (USER,)))

    def test_a_missing_sdk_fails_the_call_not_the_import(self) -> None:
        provider = GoogleProvider(api_key="gcp-test", default_model="gemini-3-flash")
        with pytest.raises(ProviderCallError, match="google-genai package"):
            provider.complete(LLMRequest("clarification", (USER,)))


class TestWiring:
    def test_three_vendors_one_interface(self) -> None:
        """The full ADR-002/ADR-006 separation, end to end: three
        vendors with three different API shapes, one port, callers
        that cannot tell them apart except by name."""
        from backcasting.infrastructure.anthropic_provider import AnthropicProvider
        from backcasting.infrastructure.openai_provider import OpenAIProvider

        def use(provider: LLMProvider, request: LLMRequest) -> LLMResponse:
            return provider.complete(request)

        request = LLMRequest("strategy-generation", (SYSTEM, USER))
        google = GoogleProvider(
            client=_client(_ok()), default_model="gemini-3-flash"
        )
        anthropic = AnthropicProvider(
            client=_anthropic_fake(), default_model="claude-sonnet-5"
        )
        openai = OpenAIProvider(
            client=_openai_fake(), default_model="gpt-5.1"
        )
        results = [use(p, request).content for p in (google, anthropic, openai)]
        assert results == ["A clear goal."] * 3
        assert [p.name for p in (google, anthropic, openai)] == [
            "google", "anthropic", "openai",
        ]


def _anthropic_fake() -> Any:
    """A minimal Anthropic-shaped fake for the side-by-side wiring."""

    class _TextBlock:
        text = "A clear goal."

    class _Usage:
        input_tokens = 100
        output_tokens = 30

    class _Response:
        content = [_TextBlock()]
        model = "claude-sonnet-5"
        usage = _Usage()

    class _Messages:
        def create(self, **kwargs):
            return _Response()

    class _Client:
        messages = _Messages()

    return _Client()


def _openai_fake() -> Any:
    """A minimal OpenAI-shaped fake for the side-by-side wiring."""

    class _Message:
        content = "A clear goal."

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]
        model = "gpt-5.1"

    class _Completions:
        def create(self, **kwargs):
            return _Response()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    return _Client()
