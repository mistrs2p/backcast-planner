"""The permission guard — an enforcing provider wrapper (docs/09).

Permission validation is only a guardrail if nothing can route
around it. This wrapper implements the provider port and checks
every request's operation against a
:class:`~backcasting.domain.tool_permissions.ToolPermissions`
allowlist before the inner provider — the one wired to a vendor —
is ever reached. A denied operation raises
:class:`~backcasting.domain.tool_permissions.ToolPermissionError`
*before* the call: no request leaves the process, so there is
nothing to audit and nothing to pay for. Vendor faults from the
inner provider propagate untouched, as everywhere else; the guard
adds a check, not a handler.

The wrapper is transparent for everything permitted: same name,
same responses, same errors — which is what makes it composable
with the retry-limited use cases in
:mod:`~backcasting.application.validated_generation`.
"""

from __future__ import annotations

from backcasting.domain.llm_provider import LLMProvider, LLMRequest, LLMResponse
from backcasting.domain.tool_permissions import ToolPermissions


class PermittedProvider(LLMProvider):
    """A provider that refuses operations the allowlist denies."""

    def __init__(self, provider: LLMProvider, permissions: ToolPermissions):
        if not isinstance(provider, LLMProvider):
            raise TypeError("provider must be an LLMProvider")
        if not isinstance(permissions, ToolPermissions):
            raise TypeError("permissions must be ToolPermissions")
        self._provider = provider
        self._permissions = permissions

    @property
    def name(self) -> str:
        return self._provider.name

    def complete(self, request: LLMRequest) -> LLMResponse:
        self._permissions.require_request(request)
        return self._provider.complete(request)
