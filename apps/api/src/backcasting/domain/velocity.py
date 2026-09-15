"""Velocity — how fast work is actually getting done.

docs/07-PROGRESS-FEEDBACK.md lists the signals the progress layer
must produce; velocity is the base rate underneath the trend and
sustainability readings: the observed work rate over a recent
window, computed purely from recorded sittings
(:class:`~backcasting.domain.execution.Execution` — the Actual of
"Planned ≠ Actual ≠ Progress").

Semantics:

- The window is calendar time — ``[at - window, at]`` — not
  workable time: velocity says how much work materialized per
  calendar day at the observed pace, and comparing that against
  capacity/availability is the sustainability layer's judgment
  (docs/07), not this measurement's.
- A sitting contributes the part of it that lies inside the window
  (clipped at both edges): work performed within the window is what
  the window's velocity is made of. Sittings ending after ``at``
  are clipped at ``at`` — facts after the measurement moment have
  not happened yet.
- ``rate`` is the dimensionless fraction of the window spent
  working; :attr:`Velocity.per_day` restates it as a timedelta of
  work per calendar day, the form projections consume (remaining
  workload ÷ per-day pace = calendar time to finish, at current
  velocity).

The empty window reads zero — no work recorded is itself the
observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from backcasting.domain.execution import Execution
from backcasting.domain.timezone import require_utc


class VelocityError(ValueError):
    """Raised when a velocity invariant is violated."""


@dataclass(frozen=True)
class Velocity:
    """The observed work rate over one window of calendar time."""

    window_start: datetime
    window_end: datetime
    worked: timedelta
    rate: float

    def __post_init__(self) -> None:
        require_utc("window_start", self.window_start, error=VelocityError)
        require_utc("window_end", self.window_end, error=VelocityError)
        if self.window_end <= self.window_start:
            raise VelocityError("window_end must be after window_start")
        if not isinstance(self.worked, timedelta) or self.worked < timedelta(0):
            raise VelocityError("worked must be a non-negative timedelta")
        if not isinstance(self.rate, (int, float)) or isinstance(self.rate, bool):
            raise VelocityError("rate must be a number")
        if not 0.0 <= self.rate <= 1.0:
            raise VelocityError("rate must be within [0, 1]")

    @property
    def per_day(self) -> timedelta:
        """The observed work per calendar day, as a timedelta."""
        span = self.window_end - self.window_start
        return (self.worked / span) * timedelta(days=1)


def compute_velocity(
    executions: tuple[Execution, ...],
    *,
    at: datetime,
    window: timedelta,
) -> Velocity:
    """Measure the work rate over ``[at - window, at]``.

    Only the part of each sitting inside the window counts, clipped
    at both edges; the ``at`` moment defaults nowhere — it is the
    measurement instant and must be explicit.
    """
    if not isinstance(executions, tuple):
        raise VelocityError("executions must be a tuple of Execution")
    for execution in executions:
        if not isinstance(execution, Execution):
            raise VelocityError("executions must be Execution instances")
    require_utc("at", at, error=VelocityError)
    if not isinstance(window, timedelta) or window <= timedelta(0):
        raise VelocityError("window must be a strictly positive timedelta")

    window_start = at - window
    worked = timedelta(0)
    for execution in executions:
        start = max(execution.start, window_start)
        end = min(execution.end, at)
        if end > start:
            worked += end - start
    rate = worked / window
    return Velocity(
        window_start=window_start,
        window_end=at,
        worked=worked,
        rate=rate,
    )
