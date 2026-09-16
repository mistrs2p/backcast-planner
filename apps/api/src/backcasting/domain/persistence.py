"""Persistence detection — the same condition, observed repeatedly.

docs/08-REPLANNING-MODEL.md, Stability Controls: "persistence
thresholds, cooldown, hysteresis". TASK-080 bounded the magnitude;
this module counts the observations. A condition that crosses a
threshold once may be noise — a bad week, a late night, a
measurement hiccup; one that *holds* for several consecutive
observations is a state of the world, and only a state of the world
is worth acting on.

The state machine is TASK-080's hysteresis run over time: an
observation enters the condition when it exceeds the enter bound,
and the condition survives the hysteresis gap (held, not flapping)
until an observation clears the exit bound. :func:`assess_persistence`
reduces a chronological sequence of observed magnitudes to where
the condition now stands — active or not, and for how many
consecutive observations it has held. A :class:`Persistence`
declares how many consecutive observations confirm it, and the
reading answers.

Cooldown (TASK-082) is the other half of stability: persistence
asks "has this held?", cooldown asks "did we just act on it?".
"""

from __future__ import annotations

from dataclasses import dataclass

from backcasting.domain.threshold import Threshold, ThresholdError


class PersistenceError(ValueError):
    """Raised when a persistence invariant is violated."""


@dataclass(frozen=True)
class Persistence:
    """The persistence threshold: how many consecutive observations
    a condition must hold before it is confirmed."""

    required: int

    def __post_init__(self) -> None:
        if not isinstance(self.required, int) or isinstance(self.required, bool):
            raise PersistenceError("required must be an integer")
        if self.required < 1:
            raise PersistenceError("required must be at least 1")


@dataclass(frozen=True)
class PersistenceReading:
    """Where a condition stands after a run of observations."""

    active: bool
    consecutive: int

    def __post_init__(self) -> None:
        if not isinstance(self.active, bool):
            raise PersistenceError("active must be a boolean")
        if not isinstance(self.consecutive, int) or isinstance(
            self.consecutive, bool
        ):
            raise PersistenceError("consecutive must be an integer")
        if self.consecutive < 0:
            raise PersistenceError("consecutive must be non-negative")
        if self.consecutive > 0 and not self.active:
            raise PersistenceError(
                "an inactive condition cannot hold for consecutive observations"
            )

    def confirms(self, persistence: Persistence) -> bool:
        """Whether the held run reaches the persistence threshold."""
        if not isinstance(persistence, Persistence):
            raise PersistenceError("persistence must be a Persistence")
        return self.consecutive >= persistence.required


def assess_persistence(
    threshold: Threshold,
    magnitudes: tuple,
) -> PersistenceReading:
    """Run the hysteresis state machine over a chronological run of
    observed magnitudes.

    Each observation, earliest first: entering wins (an observation
    at the enter bound enters or re-enters the condition, even when
    the bounds are equal and it also sits on the exit bound); an
    observation below the exit bound clears it and resets the run;
    an observation in the hysteresis gap holds it — the run counts
    on, which is the point of hysteresis: a condition that dipped
    but did not recover has not stopped being a state of the world.
    """
    if not isinstance(threshold, Threshold):
        raise PersistenceError("threshold must be a Threshold")
    if not isinstance(magnitudes, tuple):
        raise PersistenceError("magnitudes must be a tuple of observed magnitudes")

    active = False
    consecutive = 0
    for magnitude in magnitudes:
        try:
            exceeded = threshold.is_exceeded(magnitude)
            cleared = threshold.has_cleared(magnitude)
        except ThresholdError as exc:
            raise PersistenceError(str(exc)) from exc
        if exceeded:
            active = True
            consecutive += 1
        elif active and cleared:
            active = False
            consecutive = 0
        elif active:
            consecutive += 1  # held through the hysteresis gap
    return PersistenceReading(active=active, consecutive=consecutive)
