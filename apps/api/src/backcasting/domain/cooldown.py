"""Cooldown — a rest between actions.

docs/08-REPLANNING-MODEL.md, Stability Controls: "persistence
thresholds, cooldown, hysteresis, minimum-change principle".
TASK-080 bounded the magnitude, TASK-081 required it to hold; this
module times the response. A condition may persist for good
reason and re-confirm immediately after the system has acted —
cooldown keeps the system from hammering: once an action has been
taken, further actions are suppressed until its period has
elapsed.

The module is deliberately just a clock: a :class:`Cooldown`
declares the period, and :func:`in_cooldown` /
:func:`cooldown_remaining` answer for a moment in time given when
the last action happened. Which actions start which clocks (per
trigger kind, per plan, per run) is bookkeeping for the
replanning policy (TASK-083) and the decision engine (TASK-084),
not for the clock itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from backcasting.domain.timezone import require_utc


class CooldownError(ValueError):
    """Raised when a cooldown invariant is violated."""


@dataclass(frozen=True)
class Cooldown:
    """The minimum time between actions. A zero period is no
    cooldown at all."""

    period: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.period, timedelta) or self.period < timedelta(0):
            raise CooldownError("period must be a non-negative timedelta")


def in_cooldown(
    cooldown: Cooldown,
    last_action_at: datetime,
    *,
    at: datetime,
) -> bool:
    """Whether an action is still suppressed at ``at``.

    The clock runs from the last action; the moment its period
    ends, acting is free again.
    """
    if not isinstance(cooldown, Cooldown):
        raise CooldownError("cooldown must be a Cooldown")
    if not isinstance(last_action_at, datetime):
        raise CooldownError("last_action_at must be a datetime")
    require_utc("last_action_at", last_action_at, error=CooldownError)
    require_utc("at", at, error=CooldownError)
    if at < last_action_at:
        raise CooldownError("at must not precede last_action_at")
    return at < last_action_at + cooldown.period


def cooldown_remaining(
    cooldown: Cooldown,
    last_action_at: datetime,
    *,
    at: datetime,
) -> timedelta:
    """The suppressed time left at ``at``; zero when free to act."""
    if not isinstance(cooldown, Cooldown):
        raise CooldownError("cooldown must be a Cooldown")
    if not isinstance(last_action_at, datetime):
        raise CooldownError("last_action_at must be a datetime")
    require_utc("last_action_at", last_action_at, error=CooldownError)
    require_utc("at", at, error=CooldownError)
    if at < last_action_at:
        raise CooldownError("at must not precede last_action_at")
    ends_at = last_action_at + cooldown.period
    return ends_at - at if at < ends_at else timedelta(0)
