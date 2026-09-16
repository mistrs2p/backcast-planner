"""AI fallback — the graceful-degradation record (docs/09).

Every AI operation has a deterministic path behind it: strategies,
outcomes, and tasks can all be proposed by hand and accepted
through the same deterministic rules (the seam tests of
TASK-095–098 pin this by doing exactly that). So when the AI path
fails, the system does not fail — it falls back, and the record of
*that* is this module's value: :class:`Fallback`, the reason one
AI operation gave way to the deterministic path, kept as an
immutable fact with the same discipline as the verbatim proposal
records. What a fallback never does is hide the failure: the
reason is mandatory, so the audit trail always says why the AI was
bypassed.

Which failures are fallback-worthy is a policy, and the policy is
deliberate (see
:mod:`~backcasting.application.ai_fallback`): vendor faults and
proposals that never validated fall back, because the deterministic
path is a designed alternative; permission denials and programming
errors surface, because silently degrading a misconfiguration
replaces a loud bug with a quiet wrong behavior.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_REASON_LENGTH = 500


class AIFallbackError(ValueError):
    """Raised when a fallback invariant is violated."""


@dataclass(frozen=True)
class Fallback:
    """The deterministic path taken because the AI path failed,
    with the reason it did."""

    reason: str

    def __post_init__(self) -> None:
        reason = self.reason
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > MAX_REASON_LENGTH
        ):
            raise AIFallbackError(
                f"reason must be a non-empty string of at most "
                f"{MAX_REASON_LENGTH} characters"
            )
