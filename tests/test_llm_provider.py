"""Tests for the LLM provider interface (TASK-090).

The provider-neutral port of docs/09 and ADR-006: the message and
request/response vocabulary, their invariants, and the contract the
vendor adapters (TASK-091 through TASK-093) will implement.
"""

from __future__ import annotations

import pytest

from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    Message,
    MessageRole,
    ProviderCallError,
)

SYSTEM = Message(MessageRole.SYSTEM, "You help with planning.")
USER = Message(MessageRole.USER, "Interpret this goal: run a marathon.")


class TestMessage:
    def test_shape(self) -> None:
        message = Message(MessageRole.USER, "  Hello there  ")
        assert message.role is MessageRole.USER
        assert message.content == "  Hello there  "

    def test_all_three_roles(self) -> None:
        assert [role.value for role in MessageRole] == [
            "system", "user", "assistant",
        ]

    def test_rejects_bad_fields(self) -> None:
        with pytest.raises(LLMProviderError, match="role must be"):
            Message("user", "Hello")  # type: ignore[arg-type]
        with pytest.raises(LLMProviderError, match="content must be"):
            Message(MessageRole.USER, "   ")
        with pytest.raises(LLMProviderError, match="content must be"):
            Message(MessageRole.USER, 42)  # type: ignore[arg-type]

    def test_content_is_bounded(self) -> None:
        with pytest.raises(LLMProviderError, match="at most"):
            Message(MessageRole.USER, "x" * 100_001)

    def test_is_immutable(self) -> None:
        with pytest.raises(Exception):
            USER.content = "changed"  # type: ignore[misc]


class TestLLMRequest:
    def test_shape(self) -> None:
        request = LLMRequest(
            "goal-interpretation",
            (SYSTEM, USER),
            model="gpt-5.1",
            max_output_tokens=512,
            temperature=0.2,
        )
        assert request.operation == "goal-interpretation"
        assert request.messages == (SYSTEM, USER)
        assert request.model == "gpt-5.1"
        assert request.max_output_tokens == 512
        assert request.temperature == 0.2

    def test_everything_optional_is_none(self) -> None:
        """No model, no knobs: the provider's own defaults apply —
        no caller needs a vendor's catalogue to use the port."""
        request = LLMRequest("strategy-generation", (USER,))
        assert request.model is None
        assert request.max_output_tokens is None
        assert request.temperature is None

    def test_operation_is_mandatory_and_bounded(self) -> None:
        """The audit log and permission checks key on the operation
        (docs/09 guardrails); it cannot be blank or unbounded."""
        with pytest.raises(LLMProviderError, match="operation must be"):
            LLMRequest("", (USER,))
        with pytest.raises(LLMProviderError, match="operation must be"):
            LLMRequest("   ", (USER,))
        with pytest.raises(LLMProviderError, match="operation must be"):
            LLMRequest(42, (USER,))  # type: ignore[arg-type]
        with pytest.raises(LLMProviderError, match="operation must be"):
            LLMRequest("x" * 101, (USER,))

    def test_messages_must_be_a_non_empty_tuple_of_messages(self) -> None:
        with pytest.raises(LLMProviderError, match="messages must not be empty"):
            LLMRequest("goal-interpretation", ())
        with pytest.raises(LLMProviderError, match="messages must be a tuple"):
            LLMRequest("goal-interpretation", [USER])  # type: ignore[arg-type]
        with pytest.raises(LLMProviderError, match="Message instances"):
            LLMRequest("goal-interpretation", ("user",))  # type: ignore[arg-type]

    def test_model_must_be_non_empty_when_given(self) -> None:
        with pytest.raises(LLMProviderError, match="model must be"):
            LLMRequest("goal-interpretation", (USER,), model="   ")
        with pytest.raises(LLMProviderError, match="model must be"):
            LLMRequest("goal-interpretation", (USER,), model=7)  # type: ignore[arg-type]
        with pytest.raises(LLMProviderError, match="model must be"):
            LLMRequest("goal-interpretation", (USER,), model="x" * 201)

    def test_max_output_tokens_must_be_positive(self) -> None:
        for bad in (0, -1, True, "512", 512.0):
            with pytest.raises(LLMProviderError, match="max_output_tokens"):
                LLMRequest(
                    "goal-interpretation", (USER,), max_output_tokens=bad
                )

    def test_temperature_must_be_within_bounds(self) -> None:
        for bad in (-0.1, 2.1, True, "low"):
            with pytest.raises(LLMProviderError, match="temperature"):
                LLMRequest("goal-interpretation", (USER,), temperature=bad)
        # The whole neutral range is accepted, edges included.
        for good in (0.0, 1, 2.0):
            LLMRequest("goal-interpretation", (USER,), temperature=good)


class TestLLMResponse:
    def _response(self, **overrides):
        kwargs = dict(
            content="A clear goal: finish a marathon.",
            model="gpt-5.1",
        )
        kwargs.update(overrides)
        return LLMResponse(**kwargs)

    def test_shape(self) -> None:
        response = self._response(
            prompt_tokens=120, completion_tokens=40
        )
        assert response.model == "gpt-5.1"
        assert response.prompt_tokens == 120
        assert response.completion_tokens == 40

    def test_token_counts_are_optional(self) -> None:
        response = self._response()
        assert response.prompt_tokens is None
        assert response.completion_tokens is None

    def test_content_must_be_non_empty_and_bounded(self) -> None:
        with pytest.raises(LLMProviderError, match="content must be"):
            self._response(content="   ")
        with pytest.raises(LLMProviderError, match="content must be"):
            self._response(content=42)  # type: ignore[arg-type]
        with pytest.raises(LLMProviderError, match="at most"):
            self._response(content="x" * 200_001)

    def test_model_is_mandatory(self) -> None:
        """Providers resolve defaults themselves; the audit log must
        record the model that actually answered, not the request."""
        with pytest.raises(LLMProviderError, match="model must be"):
            self._response(model="")
        with pytest.raises(LLMProviderError, match="model must be"):
            self._response(model=None)  # type: ignore[arg-type]

    def test_token_counts_must_be_non_negative_integers(self) -> None:
        for bad in (-1, True, "120", 120.0):
            with pytest.raises(LLMProviderError, match="prompt_tokens"):
                self._response(prompt_tokens=bad)
            with pytest.raises(LLMProviderError, match="completion_tokens"):
                self._response(completion_tokens=bad)


class EchoProvider(LLMProvider):
    """A reference implementation: the contract an adapter keeps."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[LLMRequest] = []

    @property
    def name(self) -> str:
        return "echo"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.fail:
            raise ProviderCallError("vendor unavailable")
        return LLMResponse(
            content=f"Proposal for {request.operation}.",
            model="echo-1",
            prompt_tokens=len(request.messages),
            completion_tokens=1,
        )


class TestLLMProviderPort:
    def test_the_contract_round_trips(self) -> None:
        provider = EchoProvider()
        request = LLMRequest("goal-interpretation", (SYSTEM, USER))
        response = provider.complete(request)
        assert provider.calls == [request]
        assert response.content == "Proposal for goal-interpretation."
        assert provider.name == "echo"

    def test_vendor_failures_speak_one_error(self) -> None:
        """Whatever the SDK raised, the caller sees ProviderCallError
        — the single failure currency fallback logic will catch."""
        provider = EchoProvider(fail=True)
        with pytest.raises(ProviderCallError, match="vendor unavailable"):
            provider.complete(LLMRequest("clarification", (USER,)))

    def test_the_port_cannot_be_instantiated_directly(self) -> None:
        with pytest.raises(TypeError):
            LLMProvider()  # type: ignore[abstract]

    def test_implementations_reject_bad_requests_with_the_invariant_error(
        self,
    ) -> None:
        """A malformed request is a programming error, not provider
        trouble: the invariant error, raised before any vendor call."""
        provider = EchoProvider()
        with pytest.raises(LLMProviderError, match="messages must not be empty"):
            provider.complete(LLMRequest("task-generation", ()))
        assert provider.calls == []

    def test_the_port_stays_vendor_free(self) -> None:
        """ADR-006 / domain purity: the interface module imports
        nothing but the standard library — no vendor SDK, directly
        or through the back door."""
        import ast
        import pathlib

        import backcasting.domain.llm_provider as module

        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        imported = {
            node.name.split(".")[0]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import)
        } | {
            node.module.split(".")[0]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert imported <= {"__future__", "abc", "dataclasses", "enum"}
