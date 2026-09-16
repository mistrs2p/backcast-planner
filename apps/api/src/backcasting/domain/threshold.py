"""Thresholds — the magnitude bounds of stability.

docs/08-REPLANNING-MODEL.md, Stability Controls: "persistence
thresholds, cooldown, hysteresis, minimum-change principle". This
module is the first of those: how far a reading has to slip before
it is trigger-worthy at all. TASK-081 layers persistence on top
(the same condition, observed repeatedly); TASK-082 layers cooldown
(time between actions); the minimum-change principle belongs to the
policy (TASK-083).

A :class:`Threshold` bounds one :class:`Measure` — the shortfall
side of a variance (a duration), the utilization (a rate), or the
unfinished share of completion (a rate) — with an ``enter_bound``
the reading must reach, and an ``exit_bound`` it must fall back to
before the condition is considered cleared. Setting the two apart
is hysteresis: a reading that enters at 4 hours behind but must
recover to within 2 to clear does not flap while hovering at 3.
With the bounds equal (the default) the threshold is plain.

Thresholds bound magnitudes of badness, not the readings
themselves: the adapters (:func:`variance_shortfall`,
:func:`utilization`, :func:`completion_shortfall`) reduce a
Variance, a Sustainability, or a ProgressSnapshot to the
non-negative slip the threshold compares — a favorable variance
contributes zero, whatever its size.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from backcasting.domain.progress import ProgressSnapshot
from backcasting.domain.sustainability import Sustainability
from backcasting.domain.variance import Variance


class ThresholdError(ValueError):
    """Raised when a threshold invariant is violated."""


class Measure(str, Enum):
    """What a threshold bounds, and in what units.

    The measures are the slip magnitudes the EPIC-008 signals
    compute: durations for variance shortfalls, rates for
    utilization and completion.
    """

    SHORTFALL = "shortfall"  # timedelta: the unfavorable side of a variance
    UTILIZATION = "utilization"  # rate: worked over workable
    COMPLETION = "completion"  # rate: the unfinished share


_DURATION_MEASURES = frozenset({Measure.SHORTFALL})
_RATE_MEASURES = frozenset({Measure.UTILIZATION, Measure.COMPLETION})


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(frozen=True)
class Threshold:
    """One magnitude bound: what it guards, when it trips, when it
    clears."""

    measure: Measure
    enter_bound: timedelta | float
    exit_bound: timedelta | float | None = None  # defaults to enter_bound

    def __post_init__(self) -> None:
        if not isinstance(self.measure, Measure):
            raise ThresholdError("measure must be a Measure")
        exit_bound = (
            self.enter_bound if self.exit_bound is None else self.exit_bound
        )
        if self.measure in _DURATION_MEASURES:
            for name, bound in (("enter_bound", self.enter_bound), ("exit_bound", exit_bound)):
                if not isinstance(bound, timedelta) or bound < timedelta(0):
                    raise ThresholdError(
                        f"{name} for {self.measure.value} must be a "
                        "non-negative timedelta"
                    )
        elif self.measure in _RATE_MEASURES:
            for name, bound in (("enter_bound", self.enter_bound), ("exit_bound", exit_bound)):
                if not _is_number(bound) or bound < 0:
                    raise ThresholdError(
                        f"{name} for {self.measure.value} must be a "
                        "non-negative number"
                    )
        else:  # pragma: no cover - every Measure is in one family
            raise ThresholdError(f"{self.measure.value} has no measure family")
        if exit_bound > self.enter_bound:
            raise ThresholdError(
                "exit_bound must not exceed enter_bound — hysteresis "
                "clears at or below the level it enters"
            )
        object.__setattr__(self, "exit_bound", exit_bound)

    def is_exceeded(self, magnitude: timedelta | float) -> bool:
        """Whether the slip has reached the enter bound."""
        _check_magnitude(self.measure, magnitude)
        return magnitude >= self.enter_bound

    def has_cleared(self, magnitude: timedelta | float) -> bool:
        """Whether the slip has fallen back to the exit bound.

        Hysteresis is enter-wins: at a magnitude that both exceeds
        and clears (possible only when the bounds are equal and the
        slip sits exactly on them), an inactive condition enters
        before an active one clears.
        """
        _check_magnitude(self.measure, magnitude)
        return magnitude <= self.exit_bound


def _check_magnitude(measure: Measure, magnitude) -> None:
    if measure in _DURATION_MEASURES:
        if not isinstance(magnitude, timedelta) or magnitude < timedelta(0):
            raise ThresholdError(
                f"a {measure.value} magnitude must be a non-negative timedelta"
            )
    elif not _is_number(magnitude) or magnitude < 0:
        raise ThresholdError(
            f"a {measure.value} magnitude must be a non-negative number"
        )


def variance_shortfall(variance: Variance) -> timedelta:
    """The unfavorable side of a variance, as a non-negative slip.

    A favorable variance — ahead, under, within — contributes zero:
    its size is good news, not badness for a threshold to weigh.
    """
    if not isinstance(variance, Variance):
        raise ThresholdError("variance must be a Variance")
    if variance.favorable:
        return timedelta(0)
    return abs(variance.delta)


def utilization(reading: Sustainability) -> float:
    """The utilization a threshold weighs: worked over workable.

    A reading with no workable time carries no utilization (nothing
    was declared to be over); its magnitude is zero — the
    beyond-capacity judgement already lives in the reading's own
    status.
    """
    if not isinstance(reading, Sustainability):
        raise ThresholdError("reading must be a Sustainability")
    return reading.utilization if reading.utilization is not None else 0.0


def completion_shortfall(snapshot: ProgressSnapshot) -> float:
    """The unfinished share of the plan's tasks."""
    if not isinstance(snapshot, ProgressSnapshot):
        raise ThresholdError("snapshot must be a ProgressSnapshot")
    return 1.0 - snapshot.completion_rate
