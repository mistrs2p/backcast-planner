"""Trend analysis — which way the pace is heading, and what it implies.

docs/07-PROGRESS-FEEDBACK.md lists "trend" among the signals. Trend
sits on top of velocity (TASK-072): the recent window's work rate
against the one before it says whether the pace is accelerating,
steady, or decelerating — and the recent rate, applied to the
remaining workload, projects when the plan would finish.

Both parts are mechanical:

- the direction is a strict comparison of the two windows' rates —
  no smoothing, no tolerance; a trend statement is only as good as
  its windows are honest, and dressing the comparison in a fuzz
  band would only hide which inputs moved it;
- :func:`project_completion` scales the snapshot's remaining
  workload by the velocity window's work-to-span ratio. A finished
  plan has nothing left to project (``None``); a zero pace never
  finishes (``None``) — both are facts, not errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from backcasting.domain.progress import ProgressSnapshot
from backcasting.domain.velocity import Velocity


class TrendError(ValueError):
    """Raised when a trend invariant is violated."""


class TrendDirection(str, Enum):
    """Where the observed pace is heading."""

    ACCELERATING = "accelerating"
    STEADY = "steady"
    DECELERATING = "decelerating"


@dataclass(frozen=True)
class Trend:
    """The pace direction across two consecutive windows."""

    direction: TrendDirection
    recent: Velocity
    previous: Velocity

    def __post_init__(self) -> None:
        if not isinstance(self.direction, TrendDirection):
            raise TrendError("direction must be a TrendDirection")
        if not isinstance(self.recent, Velocity):
            raise TrendError("recent must be a Velocity")
        if not isinstance(self.previous, Velocity):
            raise TrendError("previous must be a Velocity")
        if self.recent.window_start != self.previous.window_end:
            raise TrendError("windows must be consecutive")
        if (self.recent.window_end - self.recent.window_start) != (
            self.previous.window_end - self.previous.window_start
        ):
            raise TrendError("windows must have the same length")
        rates = {
            TrendDirection.ACCELERATING: self.recent.rate > self.previous.rate,
            TrendDirection.DECELERATING: self.recent.rate < self.previous.rate,
            TrendDirection.STEADY: self.recent.rate == self.previous.rate,
        }
        if not rates[self.direction]:
            raise TrendError("direction must match the window rates")


def analyze_trend(
    velocities: tuple[Velocity, ...],
) -> Trend:
    """State the pace direction across consecutive velocity windows.

    ``velocities`` are the windows in chronological order; the last
    two are compared (earlier history is context the caller already
    holds). Fewer than two windows cannot show a direction.
    """
    if not isinstance(velocities, tuple):
        raise TrendError("velocities must be a tuple of Velocity")
    for velocity in velocities:
        if not isinstance(velocity, Velocity):
            raise TrendError("velocities must be Velocity instances")
    if len(velocities) < 2:
        raise TrendError("a trend needs at least two windows")
    previous, recent = velocities[-2], velocities[-1]
    if recent.rate > previous.rate:
        direction = TrendDirection.ACCELERATING
    elif recent.rate < previous.rate:
        direction = TrendDirection.DECELERATING
    else:
        direction = TrendDirection.STEADY
    return Trend(direction=direction, recent=recent, previous=previous)


def project_completion(snapshot: ProgressSnapshot, velocity: Velocity) -> datetime | None:
    """When the plan finishes at ``velocity``'s pace, or ``None``.

    The remaining workload scaled by the velocity window's
    work-to-span ratio, added to the snapshot's moment.
    ``None`` when the plan is already complete
    (nothing left to project) or the pace is zero (a standstill
    never finishes) — observations, not errors.
    """
    if not isinstance(snapshot, ProgressSnapshot):
        raise TrendError("snapshot must be a ProgressSnapshot")
    if not isinstance(velocity, Velocity):
        raise TrendError("velocity must be a Velocity")
    if snapshot.remaining == timedelta(0):
        return None
    if velocity.worked == timedelta(0):
        return None
    span = velocity.window_end - velocity.window_start
    return snapshot.taken_at + (snapshot.remaining / velocity.worked) * span
