"""LLM provider interface — the domain's AI boundary port.

docs/09-AI-ARCHITECTURE.md: "Vendor-specific adapters implement a
provider-neutral interface", and ADR-006 keeps it that way so models
and providers can change without rewriting the logic above them.
This module is that interface: the request/response vocabulary every
adapter speaks, and the abstract provider the application layer
calls. Per ADR-002 the boundary carries *proposals* — text the
reasoning layer produced — and nothing the domain would have to
trust: schema validation, domain validation, and permission checks
(docs/09's guardrails) all happen on this side of the port, on the
response, never inside an adapter.

Conventions, mirroring :mod:`~backcasting.domain.repositories`:

- The records are immutable; an adapter stores and returns them as
  given, identity-free — a completion is a fact of history, not an
  entity to revise.
- ``model`` and the sampling knobs are optional: ``None`` means "the
  provider's own default", so no caller has to know a vendor's
  model catalogue to use the interface.
- Implementations raise :class:`ProviderCallError` for vendor/transport
  failures (network, auth, quota) so callers never see SDK-specific
  exceptions — the single failure currency the fallback logic
  (TASK-103) will catch.
- Bad *requests* and malformed *responses* violate this module's
  invariants and raise :class:`LLMProviderError` instead: those are
  programming errors, not provider trouble.

What the interface deliberately does *not* carry: tools, function
calling, streaming, or multimodality. docs/09 lists six text
operations (goal interpretation, clarification, strategy
generation, outcome decomposition, task generation, explanations)
and the tool-permission guardrail arrives as its own task (TASK-101);
the port grows then, if it must, and not before.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

MAX_MESSAGE_LENGTH = 100_000
MAX_OPERATION_LENGTH = 100
MAX_MODEL_LENGTH = 200
MAX_CONTENT_LENGTH = 200_000


class LLMProviderError(ValueError):
    """Raised when a provider-interface invariant is violated."""


class ProviderCallError(RuntimeError):
    """Raised by implementations on vendor/transport failures."""


class MessageRole(str, Enum):
    """Who spoke one turn of the neutral conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Message:
    """One turn of the provider-neutral conversation."""

    role: MessageRole
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, MessageRole):
            raise LLMProviderError("role must be a MessageRole")
        if not isinstance(self.content, str) or not self.content.strip():
            raise LLMProviderError("content must be a non-empty string")
        if len(self.content) > MAX_MESSAGE_LENGTH:
            raise LLMProviderError(
                f"content must be at most {MAX_MESSAGE_LENGTH} characters"
            )


@dataclass(frozen=True)
class LLMRequest:
    """One provider-neutral completion request.

    ``operation`` names the AI operation this request serves (e.g.
    ``"goal-interpretation"``, docs/09's list): the audit log and the
    permission checks key on it, so it is mandatory, not decoration.
    """

    operation: str
    messages: tuple[Message, ...]
    model: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.operation, str)
            or not self.operation.strip()
            or len(self.operation) > MAX_OPERATION_LENGTH
        ):
            raise LLMProviderError(
                f"operation must be a non-empty string of at most "
                f"{MAX_OPERATION_LENGTH} characters"
            )
        if not isinstance(self.messages, tuple):
            raise LLMProviderError("messages must be a tuple of Message")
        if not self.messages:
            raise LLMProviderError("messages must not be empty")
        for message in self.messages:
            if not isinstance(message, Message):
                raise LLMProviderError("messages must be Message instances")
        if self.model is not None:
            if (
                not isinstance(self.model, str)
                or not self.model.strip()
                or len(self.model) > MAX_MODEL_LENGTH
            ):
                raise LLMProviderError(
                    f"model must be a non-empty string of at most "
                    f"{MAX_MODEL_LENGTH} characters"
                )
        if self.max_output_tokens is not None:
            if (
                not isinstance(self.max_output_tokens, int)
                or isinstance(self.max_output_tokens, bool)
                or self.max_output_tokens < 1
            ):
                raise LLMProviderError(
                    "max_output_tokens must be a positive integer"
                )
        if self.temperature is not None:
            if (
                not isinstance(self.temperature, (int, float))
                or isinstance(self.temperature, bool)
                or not 0.0 <= self.temperature <= 2.0
            ):
                raise LLMProviderError(
                    "temperature must be a number within [0, 2]"
                )


@dataclass(frozen=True)
class LLMResponse:
    """One provider-neutral completion result.

    ``content`` is the proposal, verbatim: stripped of surrounding
    whitespace but otherwise uninterpreted — reading it is the
    reasoning layer's job and the validators' (ADR-002), never the
    adapter's. ``model`` is the model that actually answered, because
    providers resolve defaults themselves and the audit log must
    record the truth rather than the request. Token counts are
    optional: some adapters cannot know them.
    """

    content: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise LLMProviderError("content must be a non-empty string")
        if len(self.content) > MAX_CONTENT_LENGTH:
            raise LLMProviderError(
                f"content must be at most {MAX_CONTENT_LENGTH} characters"
            )
        if not isinstance(self.model, str) or not self.model.strip():
            raise LLMProviderError("model must be a non-empty string")
        for name in ("prompt_tokens", "completion_tokens"):
            count = getattr(self, name)
            if count is not None and (
                not isinstance(count, int) or isinstance(count, bool) or count < 0
            ):
                raise LLMProviderError(f"{name} must be a non-negative integer")


class LLMProvider(ABC):
    """The provider-neutral AI port (docs/09, ADR-006).

    Vendor adapters (OpenAI TASK-091, Anthropic TASK-092, Google
    TASK-093) implement this contract; everything above it — the
    context builders, the operations, the validators — depends only
    on the interface, so providers and models change without
    touching them.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The provider's identity (e.g. ``"openai"``), for audit
        records and fallback routing."""

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Ask the provider for one completion of ``request``.

        Implementations translate the neutral request into their
        vendor's shape and the vendor's answer back into a neutral
        :class:`LLMResponse`; they raise :class:`ProviderCallError`
        when the vendor call itself fails, and never interpret the
        content on the way through (ADR-002).
        """
