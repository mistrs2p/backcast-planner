"""Anthropic adapter — the second vendor implementation of the LLM port.

The same isolation as the OpenAI adapter (ADR-006, TASK-091) over a
vendor whose API shape differs in kind, not just in naming:

- The system prompt is a top-level ``system`` parameter, not a
  message in the list: the adapter hoists every neutral SYSTEM
  message out of the conversation and joins them (blank-line
  separated) into that one parameter. The neutral vocabulary is
  free to place system turns anywhere; the vendor's shape is not,
  and translation is this module's job (ADR-006's whole point).
- ``max_tokens`` is required on every Anthropic call — the vendor
  has no default — while the neutral request's ``None`` means "the
  provider's default". The adapter resolves that to
  ``default_max_output_tokens`` (constructor-overridable, by default
  :data:`DEFAULT_MAX_OUTPUT_TOKENS`), so no caller above the port
  ever has to know this vendor's quirk.
- ``temperature`` passes through only when the request set it.
  Anthropic accepts a narrower range (0–1) than the neutral port's
  (0–2): an out-of-range value is passed on, rejected by the vendor,
  and surfaces as ``ProviderCallError`` — the adapter never silently
  clamps, because a silently changed sampling knob is a silently
  changed proposal (ADR-002's spirit).
- The response's ``content`` is a list of typed blocks: the adapter
  joins the text blocks' text; a response with no text at all
  produced no usable proposal and is provider trouble, not a
  malformed record. Usage counts cross as input/output tokens.

Everything else mirrors the OpenAI adapter: the SDK imports lazily
(``anthropic`` is an optional runtime dependency, not part of the
pinned core stack, ADR-007), the client is injectable for tests, an
explicit ``api_key`` and an injected client are mutually exclusive,
no secret is stored beyond the client that holds it, and every
vendor-shaped failure — network, auth, quota, malformed answer —
surfaces as
:class:`~backcasting.domain.llm_provider.ProviderCallError` with
the original exception chained, the one failure currency the
fallback logic (TASK-103) will catch.
"""

from __future__ import annotations

from typing import Any

from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    MessageRole,
    ProviderCallError,
)

DEFAULT_MAX_OUTPUT_TOKENS = 1024


class AnthropicProvider(LLMProvider):
    """The Anthropic vendor behind the neutral LLM port.

    ``client`` injects a pre-built SDK client (tests do this with a
    fake); without one the adapter builds the SDK's default client,
    optionally with an explicit ``api_key`` — otherwise the SDK reads
    its own environment. ``default_model`` resolves a request that
    leaves the model choice to the provider;
    ``default_max_output_tokens`` resolves an unset output bound
    (the vendor requires one on every call).
    """

    def __init__(
        self,
        *,
        client: Any = None,
        api_key: str | None = None,
        default_model: str | None = None,
        default_max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        if client is not None and api_key is not None:
            raise ValueError("pass a client or an api_key, not both")
        if default_model is not None and (
            not isinstance(default_model, str) or not default_model.strip()
        ):
            raise ValueError("default_model must be a non-empty string")
        if (
            not isinstance(default_max_output_tokens, int)
            or isinstance(default_max_output_tokens, bool)
            or default_max_output_tokens < 1
        ):
            raise ValueError("default_max_output_tokens must be a positive integer")
        self._client = client
        self._api_key = api_key
        self._default_model = default_model
        self._default_max_output_tokens = default_max_output_tokens

    @property
    def name(self) -> str:
        return "anthropic"

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Translate, call, translate back; failures arrive as
        ``ProviderCallError`` with the vendor exception chained."""
        model = request.model or self._default_model
        if not model:
            raise ProviderCallError(
                "no model: the request leaves the choice to the provider "
                "and this adapter has no default_model configured"
            )

        system_parts = [
            message.content
            for message in request.messages
            if message.role is MessageRole.SYSTEM
        ]
        vendor_request: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
                if message.role is not MessageRole.SYSTEM
            ],
            # The vendor requires a bound on every call; the neutral
            # request's None is resolved to this adapter's default.
            "max_tokens": (
                request.max_output_tokens or self._default_max_output_tokens
            ),
        }
        if system_parts:
            vendor_request["system"] = "\n\n".join(system_parts)
        if request.temperature is not None:
            vendor_request["temperature"] = request.temperature

        client = self._client if self._client is not None else self._default_client()
        try:
            vendor_response = client.messages.create(**vendor_request)
        except ProviderCallError:
            raise
        except Exception as exc:  # noqa: BLE001 - one currency for all vendor faults
            raise ProviderCallError(f"anthropic call failed: {exc}") from exc

        return self._translate(vendor_response)

    def _default_client(self) -> Any:
        """Build the SDK's default client, importing the SDK lazily."""
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise ProviderCallError(
                "the anthropic package is not installed; it is an optional "
                "runtime dependency of this adapter"
            ) from exc
        if self._api_key is not None:
            return anthropic.Anthropic(api_key=self._api_key)
        return anthropic.Anthropic()

    def _translate(self, vendor_response: Any) -> LLMResponse:
        """Vendor answer -> neutral response; no text blocks means
        no usable proposal — provider trouble, not a bad record."""
        blocks = getattr(vendor_response, "content", None) or []
        text = "\n\n".join(
            block.text for block in blocks if getattr(block, "text", None)
        )
        if not text.strip():
            raise ProviderCallError("anthropic returned no usable content")

        model = getattr(vendor_response, "model", None)
        if not isinstance(model, str) or not model.strip():
            raise ProviderCallError("anthropic returned no model")

        usage = getattr(vendor_response, "usage", None)
        return LLMResponse(
            content=text,
            model=model,
            prompt_tokens=getattr(usage, "input_tokens", None) if usage else None,
            completion_tokens=(
                getattr(usage, "output_tokens", None) if usage else None
            ),
        )
