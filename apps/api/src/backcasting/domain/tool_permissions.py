"""Tool permissions — the permission guardrail (docs/09).

docs/09's guardrails pair *permission validation* with a *tool
allowlist*. In this architecture the LLM has no free-form tools:
everything the reasoning layer can do is one of the six AI
operations, and every operation travels through the provider port
as an :class:`~backcasting.domain.llm_provider.LLMRequest` whose
``operation`` names it. That makes the operation name the tool, and
the allowlist a set of operation names — a deployment (or a user)
permits a subset, and permission validation answers one question
before any vendor is reached: *is this operation allowed here?*

The rules are strict, mirroring the schema guardrail's refusal to
repair: an allowlist may only name operations that exist (an
unknown name is a configuration error, caught at construction, not
a silent no-op), and a denied operation raises — there is no
read-only degradation, because an operation the caller believed
ran but quietly did not is a corrupted audit trail (ADR-002: the
Domain validates and enforces).
"""

from __future__ import annotations

from dataclasses import dataclass

from backcasting.domain.llm_provider import LLMRequest

AI_OPERATIONS = frozenset(
    {
        "goal-interpretation",
        "clarification",
        "strategy-generation",
        "outcome-decomposition",
        "task-generation",
        "explanation",
    }
)
"""Every operation the AI layer can perform — the allowlist's
universe. The names are the provider port's operation keys, kept
in lockstep with the context builder's instruction table."""

MAX_OPERATION_LENGTH = 100


class ToolPermissionError(ValueError):
    """Raised when a tool-permission invariant is violated."""


@dataclass(frozen=True)
class ToolPermissions:
    """The allowlist: which AI operations are permitted.

    An empty allowlist denies everything — a deployment with no AI
    is valid; a deployment with a typo is not.
    """

    allowed_operations: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        allowed = self.allowed_operations
        if not isinstance(allowed, frozenset):
            raise ToolPermissionError(
                "allowed_operations must be a frozenset of operation names"
            )
        for name in allowed:
            if not isinstance(name, str) or not name.strip():
                raise ToolPermissionError(
                    "allowed_operations must contain non-empty strings"
                )
            if name not in AI_OPERATIONS:
                raise ToolPermissionError(
                    f"unknown AI operation {name!r} — the known operations "
                    f"are: {', '.join(sorted(AI_OPERATIONS))}"
                )

    def permits(self, operation: str) -> bool:
        """Whether ``operation`` may run under this allowlist."""
        return operation in self.allowed_operations

    def require(self, operation: str) -> None:
        """Validate ``operation`` against the allowlist, raising
        :class:`ToolPermissionError` when it is not permitted."""
        if not isinstance(operation, str) or not operation.strip():
            raise ToolPermissionError("operation must be a non-empty string")
        if len(operation) > MAX_OPERATION_LENGTH:
            raise ToolPermissionError(
                f"operation must be at most {MAX_OPERATION_LENGTH} characters"
            )
        if not self.permits(operation):
            allowed = (
                ", ".join(sorted(self.allowed_operations))
                if self.allowed_operations
                else "none"
            )
            raise ToolPermissionError(
                f"AI operation {operation!r} is not permitted "
                f"(allowed: {allowed})"
            )

    def require_request(self, request: LLMRequest) -> None:
        """Validate a request's operation against the allowlist."""
        if not isinstance(request, LLMRequest):
            raise ToolPermissionError("request must be an LLMRequest")
        self.require(request.operation)


def grant_operations(operations: tuple[str, ...]) -> ToolPermissions:
    """The allowlist permitting exactly ``operations`` (duplicates
    collapse; unknown names are configuration errors)."""
    if not isinstance(operations, tuple):
        raise ToolPermissionError(
            "operations must be a tuple of operation names"
        )
    return ToolPermissions(frozenset(operations))


def all_operations() -> ToolPermissions:
    """The allowlist permitting every AI operation."""
    return ToolPermissions(frozenset(AI_OPERATIONS))


def no_operations() -> ToolPermissions:
    """The allowlist permitting nothing — a deployment with no AI."""
    return ToolPermissions(frozenset())
