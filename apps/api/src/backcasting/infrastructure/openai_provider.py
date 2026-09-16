"""OpenAI adapter — the first vendor implementation of the LLM port.

Isolates the OpenAI SDK behind the provider-neutral interface of
:class:`~backcasting.domain.llm_provider.LLMProvider` (ADR-006), in
the infrastructure layer where vendor code belongs (AGENTS.md §4 —
the domain stays framework/vendor independent, enforced by
``scripts/check_rules.py``). Everything above the port is written
against the interface, so this adapter can be swapped for the
Anthropic (TASK-092) or Google (TASK-093) ones — or a different
OpenAI model — without touching any of it.

Translation rules, both directions:

- Neutral ``Message`` turns become OpenAI chat messages verbatim
  (``role``/``content``) — the neutral roles are the vendor's own.
- The vendor requires a model per call, while the neutral request
  says ``None`` for "the provider's default": the adapter resolves
  that to its configured ``default_model``. A request with no model
  and an adapter with no default cannot make a call at all — that
  is call-time failure (``ProviderCallError``), not a malformed
  request, which the neutral records already ruled out at
  construction.
- ``max_output_tokens`` crosses as ``max_completion_tokens`` and
  ``temperature`` passes through, each only when the request set it;
  unset knobs stay out of the vendor call so the vendor's own
  defaults apply, exactly as the port promises.
- The response carries back ``content``, the ``model`` that actually
  answered (the request's model may have been a default), and the
  usage counts when the vendor supplied them.

The SDK is imported lazily, inside :meth:`OpenAIProvider.complete`
and the default-client helper: the ``openai`` package is an optional
runtime dependency (not part of the pinned core stack, ADR-007), so
importing this module must never crash a process that merely wires
the adapter. A missing SDK, a rejected key, a network fault — every
vendor-shaped failure surfaces as
:class:`~backcasting.domain.llm_provider.ProviderCallError`, with
the original exception chained, so callers and the fallback logic
(TASK-103) see one failure currency and never an SDK type. A vendor
answer with no choices or no usable content is provider trouble
too, for the same reason: from above the port, the call failed to
produce a proposal.

No secrets live here: the API key is passed in (or left to the
SDK's own ``OPENAI_API_KEY`` environment default) and never stored
beyond the client that holds it.
"""

from __future__ import annotations

from typing import Any

from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCallError,
)


class OpenAIProvider(LLMProvider):
    """The OpenAI vendor behind the neutral LLM port.

    ``client`` injects a pre-built SDK client (tests do this with a
    fake); without one the adapter builds the SDK's default client,
    optionally with an explicit ``api_key`` — otherwise the SDK reads
    its own environment. ``default_model`` is the model used when a
    request leaves the choice to the provider.
    """

    def __init__(
        self,
        *,
        client: Any = None,
        api_key: str | None = None,
        default_model: str | None = None,
    ) -> None:
        if client is not None and api_key is not None:
            raise ValueError("pass a client or an api_key, not both")
        if default_model is not None and (
            not isinstance(default_model, str) or not default_model.strip()
        ):
            raise ValueError("default_model must be a non-empty string")
        self._client = client
        self._api_key = api_key
        self._default_model = default_model

    @property
    def name(self) -> str:
        return "openai"

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Translate, call, translate back; failures arrive as
        ``ProviderCallError`` with the vendor exception chained."""
        model = request.model or self._default_model
        if not model:
            raise ProviderCallError(
                "no model: the request leaves the choice to the provider "
                "and this adapter has no default_model configured"
            )

        vendor_request: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
        }
        if request.max_output_tokens is not None:
            vendor_request["max_completion_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            vendor_request["temperature"] = request.temperature

        client = self._client if self._client is not None else self._default_client()
        try:
            vendor_response = client.chat.completions.create(**vendor_request)
        except ProviderCallError:
            raise
        except Exception as exc:  # noqa: BLE001 - one currency for all vendor faults
            raise ProviderCallError(f"openai call failed: {exc}") from exc

        return self._translate(vendor_response)

    def _default_client(self) -> Any:
        """Build the SDK's default client, importing the SDK lazily."""
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise ProviderCallError(
                "the openai package is not installed; it is an optional "
                "runtime dependency of this adapter"
            ) from exc
        if self._api_key is not None:
            return openai.OpenAI(api_key=self._api_key)
        return openai.OpenAI()

    def _translate(self, vendor_response: Any) -> LLMResponse:
        """Vendor answer -> neutral response; no usable content is
        provider trouble, not a malformed record."""
        choices = getattr(vendor_response, "choices", None)
        if not choices:
            raise ProviderCallError("openai returned no choices")
        content = getattr(choices[0].message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise ProviderCallError("openai returned no usable content")

        usage = getattr(vendor_response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = (
            getattr(usage, "completion_tokens", None) if usage else None
        )
        model = getattr(vendor_response, "model", None)
        if not isinstance(model, str) or not model.strip():
            raise ProviderCallError("openai returned no model")
        return LLMResponse(
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
