"""Google adapter — the third vendor implementation of the LLM port.

The same isolation as the OpenAI (TASK-091) and Anthropic (TASK-092)
adapters over Google's Gemini API (the ``google-genai`` SDK), whose
shape differs from both predecessors:

- Assistant turns speak the role ``"model"``, not ``"assistant"``:
  the adapter renames the neutral role on the way out, so nothing
  above the port ever learns the vendor's vocabulary.
- The system prompt rides in the call's ``config`` object
  (``system_instruction``), not in the contents: as with Anthropic,
  every neutral SYSTEM turn is hoisted out of the conversation and
  joined (blank-line separated) into that one instruction. A request
  with only system turns has no conversation to send — that fails
  the call up front with the one failure currency, before any vendor
  round trip.
- Sampling knobs (``temperature``, ``max_output_tokens``) also live
  in ``config``, and each is included only when the request set it:
  Gemini imposes no required output bound (unlike Anthropic), so an
  unset bound simply stays out of the config and the vendor's own
  default applies, exactly as the port promises. Out-of-range values
  are passed on, never clamped — a silently changed knob is a
  silently changed proposal.
- The response exposes ``text`` as a property that *raises* when no
  text came back (safety refusal, empty candidates): the adapter
  catches that and states it as provider trouble; the caller above
  the port sees one currency, never a vendor exception. Usage counts
  cross from ``usage_metadata`` (prompt/candidates token counts).

Everything else mirrors the sibling adapters: the SDK imports lazily
(``google-genai`` is an optional runtime dependency, not part of the
pinned core stack, ADR-007), the client is injectable for tests, an
explicit ``api_key`` and an injected client are mutually exclusive,
no secret is stored beyond the client that holds it, and every
vendor-shaped failure surfaces as
:class:`~backcasting.domain.llm_provider.ProviderCallError` with the
original exception chained — the one failure currency the fallback
logic (TASK-103) will catch.
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

# The vendor speaks "model" where the neutral port says "assistant".
_VENDOR_ASSISTANT_ROLE = "model"


class GoogleProvider(LLMProvider):
    """The Google (Gemini) vendor behind the neutral LLM port.

    ``client`` injects a pre-built SDK client (tests do this with a
    fake); without one the adapter builds the SDK's default client,
    optionally with an explicit ``api_key`` — otherwise the SDK reads
    its own environment. ``default_model`` resolves a request that
    leaves the model choice to the provider.
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
        return "google"

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Translate, call, translate back; failures arrive as
        ``ProviderCallError`` with the vendor exception chained."""
        model = request.model or self._default_model
        if not model:
            raise ProviderCallError(
                "no model: the request leaves the choice to the provider "
                "and this adapter has no default_model configured"
            )

        contents = [
            {
                "role": (
                    _VENDOR_ASSISTANT_ROLE
                    if message.role is MessageRole.ASSISTANT
                    else message.role.value
                ),
                "parts": [{"text": message.content}],
            }
            for message in request.messages
            if message.role is not MessageRole.SYSTEM
        ]
        if not contents:
            raise ProviderCallError(
                "no conversation turns to send: the request carries only "
                "system messages"
            )

        config: dict[str, Any] = {}
        system_parts = [
            message.content
            for message in request.messages
            if message.role is MessageRole.SYSTEM
        ]
        if system_parts:
            config["system_instruction"] = "\n\n".join(system_parts)
        if request.max_output_tokens is not None:
            config["max_output_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            config["temperature"] = request.temperature

        client = self._client if self._client is not None else self._default_client()
        try:
            vendor_response = client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except ProviderCallError:
            raise
        except Exception as exc:  # noqa: BLE001 - one currency for all vendor faults
            raise ProviderCallError(f"google call failed: {exc}") from exc

        return self._translate(vendor_response)

    def _default_client(self) -> Any:
        """Build the SDK's default client, importing the SDK lazily."""
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise ProviderCallError(
                "the google-genai package is not installed; it is an "
                "optional runtime dependency of this adapter"
            ) from exc
        if self._api_key is not None:
            return genai.Client(api_key=self._api_key)
        return genai.Client()

    def _translate(self, vendor_response: Any) -> LLMResponse:
        """Vendor answer -> neutral response. The vendor's ``text``
        property raises when nothing came back (safety refusal,
        empty candidates); that is provider trouble, not a malformed
        record, and it must not escape as a vendor exception."""
        try:
            text = vendor_response.text
        except Exception as exc:  # noqa: BLE001 - the property itself raises
            raise ProviderCallError(
                f"google returned no usable content: {exc}"
            ) from exc
        if not isinstance(text, str) or not text.strip():
            raise ProviderCallError("google returned no usable content")

        model = getattr(vendor_response, "model_version", None) or getattr(
            vendor_response, "model", None
        )
        if not isinstance(model, str) or not model.strip():
            raise ProviderCallError("google returned no model")

        usage = getattr(vendor_response, "usage_metadata", None)
        return LLMResponse(
            content=text,
            model=model,
            prompt_tokens=(
                getattr(usage, "prompt_token_count", None) if usage else None
            ),
            completion_tokens=(
                getattr(usage, "candidates_token_count", None) if usage else None
            ),
        )
