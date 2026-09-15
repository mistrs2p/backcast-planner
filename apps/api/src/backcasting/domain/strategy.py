"""Strategy domain model.

A Strategy is the method of movement toward the destination
(``docs/02-CONCEPTUAL-MODEL.md`` "Planning Layer"). The backcasting
pipeline *generates candidate strategies* (step 8) and then *selects one*
(step 9) — ``docs/04-BACKCASTING-MODEL.md`` — so strategies are proposed
against a backcasting run, start as CANDIDATE, and end as SELECTED or
REJECTED.

Rules:

- IDs are UUIDs; ``run_id``/``goal_id`` reference the run that generated
  the strategy and the goal it serves.
- ``name`` is non-empty, stripped, ≤ 200 characters; ``rationale`` is
  optional free text ≤ 5000 characters.
- Lifecycle: CANDIDATE → SELECTED/REJECTED, one-shot; terminal statuses
  are final.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
- :func:`propose_strategy` only accepts a RUNNING run whose goal matches —
  strategies are generated *during* a run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum

from backcasting.domain.backcasting_run import BackcastingRun, BackcastingRunStatus

MAX_NAME_LENGTH = 200
MAX_RATIONALE_LENGTH = 5000


class StrategyError(ValueError):
    """Raised when a Strategy invariant is violated."""


class StrategyStatus(str, Enum):
    """Lifecycle states of a Strategy (docs/04 pipeline steps 8–9)."""

    CANDIDATE = "candidate"
    SELECTED = "selected"
    REJECTED = "rejected"


STRATEGY_TRANSITIONS: dict[StrategyStatus, frozenset[StrategyStatus]] = {
    StrategyStatus.CANDIDATE: frozenset({StrategyStatus.SELECTED, StrategyStatus.REJECTED}),
    StrategyStatus.SELECTED: frozenset(),
    StrategyStatus.REJECTED: frozenset(),
}

TERMINAL_STRATEGY_STATUSES = frozenset(
    {StrategyStatus.SELECTED, StrategyStatus.REJECTED}
)


class InvalidStrategyTransition(StrategyError):
    """Raised when a Strategy status transition violates the lifecycle."""

    def __init__(self, from_status: StrategyStatus, to_status: StrategyStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"illegal strategy transition: {from_status.value} -> {to_status.value}"
        )


@dataclass(frozen=True)
class Strategy:
    """A proposed method of movement toward a goal's destination."""

    strategy_id: uuid.UUID
    run_id: uuid.UUID
    goal_id: uuid.UUID
    name: str
    rationale: str = ""
    status: StrategyStatus = StrategyStatus.CANDIDATE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_id, uuid.UUID):
            raise StrategyError("strategy_id must be a UUID")
        if not isinstance(self.run_id, uuid.UUID):
            raise StrategyError("run_id must be a UUID")
        if not isinstance(self.goal_id, uuid.UUID):
            raise StrategyError("goal_id must be a UUID")
        name = self.name
        if not isinstance(name, str) or not name.strip():
            raise StrategyError("name must be a non-empty string")
        if len(name.strip()) > MAX_NAME_LENGTH:
            raise StrategyError(f"name must be at most {MAX_NAME_LENGTH} characters")
        object.__setattr__(self, "name", name.strip())
        rationale = self.rationale
        if rationale is None:
            rationale = ""
        if not isinstance(rationale, str):
            raise StrategyError("rationale must be a string")
        if len(rationale) > MAX_RATIONALE_LENGTH:
            raise StrategyError(
                f"rationale must be at most {MAX_RATIONALE_LENGTH} characters"
            )
        object.__setattr__(self, "rationale", rationale)
        if not isinstance(self.status, StrategyStatus):
            raise StrategyError("status must be a StrategyStatus")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise StrategyError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise StrategyError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise StrategyError("updated_at must not precede created_at")


def propose_strategy(
    run: BackcastingRun,
    name: str,
    *,
    rationale: str = "",
    strategy_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Strategy:
    """Propose a candidate strategy during a RUNNING run.

    The run must still be running (strategies are generated as part of the
    pipeline) and the strategy is bound to the run's goal.
    """
    if not isinstance(run, BackcastingRun):
        raise TypeError("run must be a BackcastingRun")
    if run.status is not BackcastingRunStatus.RUNNING:
        raise StrategyError(
            f"cannot propose strategies for a run with status {run.status.value}"
        )
    now = created_at if created_at is not None else datetime.now(timezone.utc)
    return Strategy(
        strategy_id=strategy_id if strategy_id is not None else uuid.uuid4(),
        run_id=run.run_id,
        goal_id=run.goal_id,
        name=name,
        rationale=rationale,
        status=StrategyStatus.CANDIDATE,
        created_at=now,
        updated_at=now,
    )


def decide_strategy(
    strategy: Strategy,
    to_status: StrategyStatus,
    *,
    at: datetime | None = None,
) -> Strategy:
    """Return ``strategy`` moved to SELECTED or REJECTED, advancing ``updated_at``.

    Raises :class:`InvalidStrategyTransition` for anything else, including
    same-status transitions and moves out of a terminal state.
    """
    if not isinstance(to_status, StrategyStatus):
        raise StrategyError("to_status must be a StrategyStatus")
    if to_status not in STRATEGY_TRANSITIONS[strategy.status]:
        raise InvalidStrategyTransition(strategy.status, to_status)
    decided_at = at if at is not None else datetime.now(timezone.utc)
    return replace(strategy, status=to_status, updated_at=decided_at)


@dataclass(frozen=True)
class StrategyProposal:
    """A raw strategy proposal as an AI adapter emits it.

    The domain does not generate strategies (``docs/09-AI-ARCHITECTURE.md``:
    "The LLM proposes and reasons; the Domain validates and enforces");
    it accepts proposals through :func:`accept_proposed_strategies`, which
    applies the deterministic rules.
    """

    name: str
    rationale: str = ""

    def __post_init__(self) -> None:
        name = self.name
        if not isinstance(name, str) or not name.strip():
            raise StrategyError("proposal name must be a non-empty string")
        if len(name.strip()) > MAX_NAME_LENGTH:
            raise StrategyError(
                f"proposal name must be at most {MAX_NAME_LENGTH} characters"
            )
        object.__setattr__(self, "name", name.strip())
        rationale = self.rationale
        if rationale is None:
            rationale = ""
        if not isinstance(rationale, str):
            raise StrategyError("proposal rationale must be a string")
        if len(rationale) > MAX_RATIONALE_LENGTH:
            raise StrategyError(
                f"proposal rationale must be at most {MAX_RATIONALE_LENGTH} characters"
            )
        object.__setattr__(self, "rationale", rationale)


def accept_proposed_strategies(
    run: BackcastingRun,
    proposals: tuple[StrategyProposal, ...],
    *,
    at: datetime | None = None,
) -> tuple[Strategy, ...]:
    """Accept AI-proposed strategies as run candidates (pipeline step 8).

    Deterministic rules enforced here:

    - The run must be RUNNING (strategies are generated during the run).
    - At least one proposal must be supplied — an empty generation is a
      failed step, not a valid outcome.
    - Candidate names must be unique within the batch.
    - Every proposal must itself be valid (bounded, non-empty name).

    Returns the recorded candidates in proposal order, sharing ``at`` as
    their creation time.
    """
    if not isinstance(run, BackcastingRun):
        raise TypeError("run must be a BackcastingRun")
    if not isinstance(proposals, tuple):
        raise StrategyError("proposals must be a tuple of StrategyProposal")
    if run.status is not BackcastingRunStatus.RUNNING:
        raise StrategyError(
            f"cannot accept strategies for a run with status {run.status.value}"
        )
    if not proposals:
        raise StrategyError("at least one strategy proposal is required")
    names: set[str] = set()
    for proposal in proposals:
        if not isinstance(proposal, StrategyProposal):
            raise StrategyError("proposals must be StrategyProposal instances")
        if proposal.name in names:
            raise StrategyError(f"duplicate strategy name: {proposal.name}")
        names.add(proposal.name)
    return tuple(
        propose_strategy(
            run,
            proposal.name,
            rationale=proposal.rationale,
            created_at=at,
        )
        for proposal in proposals
    )
