"""Plan explanation — the AI's plain-language voice.

docs/09 lists "explanations/coaching" as the sixth AI operation:
given the plan and its progress, explain in plain language where
the plan stands and what comes next. Unlike the five proposal
operations, nothing here feeds a deterministic half — the
explanation is the product — so the record is the whole capability:
the LLM's words kept verbatim with their provenance, exactly as
:mod:`~backcasting.domain.goal_interpretation` and its siblings
keep their proposals. The domain does not interpret or re-derive
the explanation (ADR-002); it records it.

The record is tied to both the plan it explains and the exact
snapshot it reads — a fresh reading deserves a fresh explanation,
and the audit trail must show which point in time was explained.
Like every observation, an explanation is an immutable fact of
history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from backcasting.domain.timezone import UTC, require_utc

MAX_PROPOSAL_LENGTH = 20_000
MAX_PROVIDER_LENGTH = 100
MAX_MODEL_LENGTH = 200


class PlanExplanationError(ValueError):
    """Raised when a plan-explanation invariant is violated."""


@dataclass(frozen=True)
class PlanExplanation:
    """One AI explanation of a plan against a progress snapshot,
    verbatim, with its provenance."""

    explanation_id: uuid.UUID
    plan_id: uuid.UUID
    snapshot_id: uuid.UUID
    proposal: str
    provider: str
    model: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.explanation_id, uuid.UUID):
            raise PlanExplanationError("explanation_id must be a UUID")
        for name in ("plan_id", "snapshot_id"):
            if not isinstance(getattr(self, name), uuid.UUID):
                raise PlanExplanationError(f"{name} must be a UUID")
        proposal = self.proposal
        if (
            not isinstance(proposal, str)
            or not proposal.strip()
            or len(proposal) > MAX_PROPOSAL_LENGTH
        ):
            raise PlanExplanationError(
                f"proposal must be a non-empty string of at most "
                f"{MAX_PROPOSAL_LENGTH} characters"
            )
        for name, bound in (
            ("provider", MAX_PROVIDER_LENGTH),
            ("model", MAX_MODEL_LENGTH),
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > bound
            ):
                raise PlanExplanationError(
                    f"{name} must be a non-empty string of at most "
                    f"{bound} characters"
                )
        require_utc("created_at", self.created_at, error=PlanExplanationError)


def record_plan_explanation(
    plan_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    proposal: str,
    *,
    provider: str,
    model: str,
    created_at: datetime | None = None,
    explanation_id: uuid.UUID | None = None,
) -> PlanExplanation:
    """Record one explanation of ``plan_id`` against ``snapshot_id``
    from ``provider``'s ``model``, verbatim and with provenance
    (default: now)."""
    return PlanExplanation(
        explanation_id=explanation_id
        if explanation_id is not None
        else uuid.uuid4(),
        plan_id=plan_id,
        snapshot_id=snapshot_id,
        proposal=proposal,
        provider=provider,
        model=model,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def explanations_for_plan(
    explanations: tuple[PlanExplanation, ...],
    plan_id: uuid.UUID,
) -> tuple[PlanExplanation, ...]:
    """The explanations of one plan, in input order."""
    if not isinstance(explanations, tuple):
        raise PlanExplanationError(
            "explanations must be a tuple of PlanExplanation"
        )
    for explanation in explanations:
        if not isinstance(explanation, PlanExplanation):
            raise PlanExplanationError(
                "explanations must be PlanExplanation instances"
            )
    if not isinstance(plan_id, uuid.UUID):
        raise PlanExplanationError("plan_id must be a UUID")
    return tuple(
        explanation
        for explanation in explanations
        if explanation.plan_id == plan_id
    )
