"""Replanning policy — the assembled stance on responding.

docs/08-REPLANNING-MODEL.md fixes the vocabulary this module
assembles: three levels (Reschedule — move time only; Replan —
modify the execution plan while preserving Goal/Future; Goal
Revision — explicitly change the destination), three modes
(Manual, Suggest, Automatic), and the stability controls
(TASK-080 through TASK-082).

A :class:`ReplanningPolicy` is one plan's stance: its mode, its
cooldown, and the persistence its conditions must show before they
count. The policy gates, it does not choose — *which* level a
condition warrants is the decision engine's judgement (TASK-084);
the policy answers what the system may *do* about it and when:

- Manual: the user replans; the system never acts and never
  proposes.
- Suggest: the system proposes, the user acts.
- Automatic: the system acts on the lower levels itself — and a
  goal revision is never automatic. docs/08 calls level 3
  "explicitly change the destination": the destination is the
  user's, so even an automatic policy may at most carry a
  suggestion to revise it.

Both acting and suggesting are cooled down — a suggestion the user
has just declined is not repeated hourly any more than an action
is re-taken. The :func:`minimal_level` function is the
minimum-change principle (docs/08's fourth stability control): when
several levels could address a condition, the lowest wins, the
same ladder docs/06 already fixes for conflicts ("reschedule first;
escalate to replanning only when Plan-level feasibility is
affected").

The trace of what a replan changed is the plan version
(:mod:`~backcasting.domain.plan_version`); the levels here say
which kind of change it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from backcasting.domain.cooldown import Cooldown, in_cooldown
from backcasting.domain.persistence import Persistence
from backcasting.domain.timezone import require_utc


class ReplanningPolicyError(ValueError):
    """Raised when a replanning-policy invariant is violated."""


class ReplanningLevel(str, Enum):
    """The three levels of adaptation (docs/08)."""

    RESCHEDULE = "reschedule"  # move time only
    REPLAN = "replan"  # modify the execution plan; Goal/Future preserved
    GOAL_REVISION = "goal_revision"  # explicitly change the destination


class ReplanningMode(str, Enum):
    """The three modes (docs/08)."""

    MANUAL = "manual"
    SUGGEST = "suggest"
    AUTOMATIC = "automatic"


class ReplanScope(str, Enum):
    """How much of the execution plan a replan touches, narrowest
    first: one task (local, TASK-085), a related group (regional,
    TASK-086), or the whole plan (global, TASK-087). All three are
    level 2 — the Goal/Future stay untouched."""

    LOCAL = "local"
    REGIONAL = "regional"
    GLOBAL = "global"


_LEVEL_ORDER = (
    ReplanningLevel.RESCHEDULE,
    ReplanningLevel.REPLAN,
    ReplanningLevel.GOAL_REVISION,
)


@dataclass(frozen=True)
class ReplanningPolicy:
    """One plan's stance: how its conditions may be responded to."""

    mode: ReplanningMode
    cooldown: Cooldown
    persistence: Persistence

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ReplanningMode):
            raise ReplanningPolicyError("mode must be a ReplanningMode")
        if not isinstance(self.cooldown, Cooldown):
            raise ReplanningPolicyError("cooldown must be a Cooldown")
        if not isinstance(self.persistence, Persistence):
            raise ReplanningPolicyError("persistence must be a Persistence")

    def permits(
        self,
        level: ReplanningLevel,
        *,
        last_offered_at: datetime | None,
        at: datetime,
    ) -> bool:
        """Whether the system itself may take this action at ``at``.

        Only the Automatic mode acts, only on the lower levels, and
        only outside cooldown. ``last_offered_at`` is when this level
        was last acted on or suggested; ``None`` means never.
        """
        _check_level(level)
        require_utc("at", at, error=ReplanningPolicyError)
        if last_offered_at is not None:
            require_utc("last_offered_at", last_offered_at, error=ReplanningPolicyError)
        if self.mode is not ReplanningMode.AUTOMATIC:
            return False
        if level is ReplanningLevel.GOAL_REVISION:
            return False  # the destination is the user's (docs/08)
        if last_offered_at is None:
            return True
        return not in_cooldown(self.cooldown, last_offered_at, at=at)

    def suggests(
        self,
        level: ReplanningLevel,
        *,
        last_offered_at: datetime | None,
        at: datetime,
    ) -> bool:
        """Whether the system may propose this action at ``at``.

        Only the Suggest mode proposes — Manual neither acts nor
        proposes, and Automatic has no need to suggest what it may
        do. Proposals are cooled down like actions: a suggestion
        the user has just seen is not repeated hourly.
        """
        _check_level(level)
        require_utc("at", at, error=ReplanningPolicyError)
        if last_offered_at is not None:
            require_utc("last_offered_at", last_offered_at, error=ReplanningPolicyError)
        if self.mode is not ReplanningMode.SUGGEST:
            return False
        if last_offered_at is None:
            return True
        return not in_cooldown(self.cooldown, last_offered_at, at=at)


def _check_level(level: ReplanningLevel) -> None:
    if not isinstance(level, ReplanningLevel):
        raise ReplanningPolicyError("level must be a ReplanningLevel")


def minimal_level(levels: tuple[ReplanningLevel, ...]) -> ReplanningLevel | None:
    """The minimum-change principle: when several levels could
    address a condition, the lowest wins — reschedule before replan
    before goal revision. ``None`` when no level is in play.
    """
    if not isinstance(levels, tuple):
        raise ReplanningPolicyError("levels must be a tuple of ReplanningLevel")
    for level in levels:
        _check_level(level)
    lowest: ReplanningLevel | None = None
    for level in _LEVEL_ORDER:
        if level in levels:
            lowest = level
            break
    return lowest
