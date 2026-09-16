"""Replanning decision engine — proposal in, decision out.

The last joint of docs/08's adaptation machinery. Upstream, the
signals state their readings (variance, goal health, trend,
sustainability, feedback), the thresholds bound them, persistence
confirms them, and the reasoning layer — per ADR-002, "the LLM
proposes and reasons" — names which levels of response could
address the condition. Here the Domain "validates and enforces":
:func:`decide_response` takes the candidate levels and the
confirmed condition, applies the minimum-change principle
(:func:`~backcasting.domain.replanning_policy.minimal_level` —
the lowest level that addresses the condition wins), and runs the
policy's gates (:meth:`~backcasting.domain.replanning_policy.ReplanningPolicy.permits`
/ `suggests`, cooldown included) to produce one
:class:`ReplanningDecision`: act, suggest, or hold — with a
machine-readable reason naming which control decided.

The engine never invents a level: it only chooses among the
candidates it is given, and only when the condition has persisted.
Executing the chosen level is downstream — rescheduling for level
1 (:mod:`~backcasting.domain.rescheduling`), the replan scopes for
level 2 (TASK-085 through TASK-087), the user for level 3 — and
the trace lands in a plan version
(:mod:`~backcasting.domain.plan_version`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from backcasting.domain.cooldown import in_cooldown
from backcasting.domain.persistence import PersistenceReading
from backcasting.domain.replanning_policy import (
    ReplanningLevel,
    ReplanningMode,
    ReplanningPolicy,
    minimal_level,
)
from backcasting.domain.timezone import require_utc


class DecisionEngineError(ValueError):
    """Raised when a decision-engine invariant is violated."""


class DecisionAction(str, Enum):
    """What the system does with the chosen level."""

    ACT = "act"  # the system takes the action itself
    SUGGEST = "suggest"  # the system proposes; the user decides
    HOLD = "hold"  # do nothing now


@dataclass(frozen=True)
class ReplanningDecision:
    """One response decision, with the reason that produced it."""

    action: DecisionAction
    level: ReplanningLevel | None
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.action, DecisionAction):
            raise DecisionEngineError("action must be a DecisionAction")
        if self.level is not None and not isinstance(self.level, ReplanningLevel):
            raise DecisionEngineError("level must be a ReplanningLevel or None")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise DecisionEngineError("reason must be a non-empty string")
        if self.action is not DecisionAction.HOLD and self.level is None:
            raise DecisionEngineError(
                "acting and suggesting require a level; only holding may go without"
            )


def decide_response(
    policy: ReplanningPolicy,
    reading: PersistenceReading,
    levels: tuple[ReplanningLevel, ...],
    *,
    last_offered_at: datetime | None = None,
    at: datetime,
) -> ReplanningDecision:
    """Reduce a confirmed condition and its candidate levels to one
    decision.

    ``levels`` are the response levels the reasoning layer proposed;
    the engine picks the minimum among them, demands the reading
    confirm against the policy's own persistence, and lets the
    policy's mode and cooldown gates say what happens: act,
    suggest, or hold — with the reason naming the control that
    decided ("not-persistent", "no-candidate", "manual-mode",
    "cooldown", "goal-revision-requires-user").
    """
    if not isinstance(policy, ReplanningPolicy):
        raise DecisionEngineError("policy must be a ReplanningPolicy")
    if not isinstance(reading, PersistenceReading):
        raise DecisionEngineError("reading must be a PersistenceReading")
    if not isinstance(levels, tuple):
        raise DecisionEngineError("levels must be a tuple of ReplanningLevel")
    for level in levels:
        if not isinstance(level, ReplanningLevel):
            raise DecisionEngineError("levels must be ReplanningLevel instances")
    require_utc("at", at, error=DecisionEngineError)
    if last_offered_at is not None:
        require_utc("last_offered_at", last_offered_at, error=DecisionEngineError)

    if not reading.confirms(policy.persistence):
        return ReplanningDecision(DecisionAction.HOLD, None, "not-persistent")

    level = minimal_level(levels)
    if level is None:
        return ReplanningDecision(DecisionAction.HOLD, None, "no-candidate")

    if policy.permits(level, last_offered_at=last_offered_at, at=at):
        return ReplanningDecision(
            DecisionAction.ACT, level, f"act-{level.value}"
        )
    if policy.suggests(level, last_offered_at=last_offered_at, at=at):
        return ReplanningDecision(
            DecisionAction.SUGGEST, level, f"suggest-{level.value}"
        )

    # Holding: name the control that decided.
    if policy.mode is ReplanningMode.MANUAL:
        return ReplanningDecision(DecisionAction.HOLD, level, "manual-mode")
    if (
        last_offered_at is not None
        and in_cooldown(policy.cooldown, last_offered_at, at=at)
    ):
        return ReplanningDecision(DecisionAction.HOLD, level, "cooldown")
    if level is ReplanningLevel.GOAL_REVISION:
        return ReplanningDecision(
            DecisionAction.HOLD, level, "goal-revision-requires-user"
        )
    raise DecisionEngineError(  # pragma: no cover - every gate above names its reason
        f"no reason found for holding {level.value}"
    )
