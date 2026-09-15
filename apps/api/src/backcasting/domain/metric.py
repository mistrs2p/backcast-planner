"""Metric abstraction for measurable progress.

``docs/07-PROGRESS-FEEDBACK.md`` requires measurements to support count,
duration, percentage, boolean, and score kinds (with composite metrics as a
future extension), and variance to be *interpreted according to metric
direction: maximize, minimize, target*.

This module provides:

- :class:`MetricKind` — the five supported measurement kinds, each with its
  own value validation.
- :class:`MetricDirection` — how "better" relates to the value.
- :class:`Metric` — a named, typed metric definition (a milestone or outcome
  references these to become measurable).
- :func:`validate_metric_value` — per-kind value validation.
- :class:`Variance` / :func:`interpret_variance` — the planned-vs-actual
  difference together with its direction-aware favourability.

Value typing per kind:

- ``count``     — ``int`` (bool excluded), ≥ 0.
- ``duration``  — ``datetime.timedelta``, ≥ 0.
- ``percentage``— ``int`` or ``float`` (bool excluded), 0 ≤ v ≤ 100.
- ``boolean``   — ``bool``.
- ``score``     — ``int`` or ``float`` (bool excluded), finite, within the
  metric's explicit ``[score_min, score_max]`` scale.

Composite metrics are deliberately absent (spec marks them future work).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

MAX_METRIC_NAME_LENGTH = 200


class MetricError(ValueError):
    """Raised when a metric invariant is violated."""


class MetricKind(str, Enum):
    """Supported measurement kinds (docs/07-PROGRESS-FEEDBACK.md)."""

    COUNT = "count"
    DURATION = "duration"
    PERCENTAGE = "percentage"
    BOOLEAN = "boolean"
    SCORE = "score"


class MetricDirection(str, Enum):
    """How a metric's value relates to "better" (docs/07)."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"
    TARGET = "target"


def _is_real_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_metric_value(
    kind: MetricKind,
    value: object,
    *,
    score_min: float | None = None,
    score_max: float | None = None,
) -> object:
    """Validate ``value`` against ``kind``, returning it unchanged.

    ``score_min``/``score_max`` apply only to :attr:`MetricKind.SCORE` and
    are required for it.
    """
    if not isinstance(kind, MetricKind):
        raise MetricError("kind must be a MetricKind")
    if kind is MetricKind.COUNT:
        if not isinstance(value, int) or isinstance(value, bool):
            raise MetricError(f"count value must be an integer, got {type(value).__name__}")
        if value < 0:
            raise MetricError(f"count value must be >= 0, got {value}")
    elif kind is MetricKind.DURATION:
        if not isinstance(value, timedelta):
            raise MetricError(
                f"duration value must be a timedelta, got {type(value).__name__}"
            )
        if value < timedelta(0):
            raise MetricError(f"duration value must be >= 0, got {value}")
    elif kind is MetricKind.PERCENTAGE:
        if not _is_real_number(value):
            raise MetricError(
                f"percentage value must be a number, got {type(value).__name__}"
            )
        if not math.isfinite(float(value)):
            raise MetricError("percentage value must be finite")
        if not 0 <= float(value) <= 100:
            raise MetricError(f"percentage value must be within [0, 100], got {value}")
    elif kind is MetricKind.BOOLEAN:
        if not isinstance(value, bool):
            raise MetricError(
                f"boolean value must be a bool, got {type(value).__name__}"
            )
    elif kind is MetricKind.SCORE:
        if not _is_real_number(value):
            raise MetricError(
                f"score value must be a number, got {type(value).__name__}"
            )
        if not math.isfinite(float(value)):
            raise MetricError("score value must be finite")
        if score_min is None or score_max is None:
            raise MetricError("score metrics require an explicit score scale")
        if not score_min < score_max:
            raise MetricError("score scale must satisfy score_min < score_max")
        if not score_min <= float(value) <= score_max:
            raise MetricError(
                f"score value must be within [{score_min}, {score_max}], got {value}"
            )
    return value


@dataclass(frozen=True)
class Metric:
    """A named, typed metric definition.

    A ``TARGET`` direction requires ``target_value``; a ``SCORE`` kind
    requires an explicit ``score_min``/``score_max`` scale.
    """

    name: str
    kind: MetricKind
    direction: MetricDirection
    target_value: object = None
    score_min: float | None = None
    score_max: float | None = None
    metric_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        name = self.name
        if not isinstance(name, str) or not name.strip():
            raise MetricError("name must be a non-empty string")
        if len(name.strip()) > MAX_METRIC_NAME_LENGTH:
            raise MetricError(
                f"name must be at most {MAX_METRIC_NAME_LENGTH} characters"
            )
        object.__setattr__(self, "name", name.strip())
        if not isinstance(self.kind, MetricKind):
            raise MetricError("kind must be a MetricKind")
        if not isinstance(self.direction, MetricDirection):
            raise MetricError("direction must be a MetricDirection")
        if self.metric_id is not None and not isinstance(self.metric_id, uuid.UUID):
            raise MetricError("metric_id must be a UUID or None")
        if self.direction is MetricDirection.TARGET:
            if self.target_value is None:
                raise MetricError("target direction requires a target_value")
            self._checked(self.target_value)
        elif self.target_value is not None:
            raise MetricError("only the target direction may carry a target_value")
        if self.kind is MetricKind.SCORE:
            if self.score_min is None or self.score_max is None:
                raise MetricError("score metrics require score_min and score_max")
            if not self.score_min < self.score_max:
                raise MetricError("score scale must satisfy score_min < score_max")
            if not _is_real_number(self.score_min) or not _is_real_number(
                self.score_max
            ):
                raise MetricError("score scale bounds must be numbers")
        elif self.score_min is not None or self.score_max is not None:
            raise MetricError("only score metrics may carry a score scale")

    def _checked(self, value: object) -> object:
        """Validate a value against this metric's kind (and scale)."""
        return validate_metric_value(
            self.kind, value, score_min=self.score_min, score_max=self.score_max
        )

    def validate(self, value: object) -> object:
        """Validate a measurement value against this metric."""
        return self._checked(value)


def _numeric(value: object) -> float:
    """Coerce a validated metric value to a number for variance math."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, timedelta):
        return value.total_seconds()
    return float(value)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Variance:
    """A planned-vs-actual difference with direction-aware favourability.

    ``delta`` is ``actual - planned`` (seconds for durations); ``favorable``
    applies the metric's direction: maximize wants delta ≥ 0, minimize wants
    delta ≤ 0, target wants delta == 0.
    """

    metric: Metric
    planned: object
    actual: object
    delta: float
    favorable: bool


def interpret_variance(metric: Metric, planned: object, actual: object) -> Variance:
    """Compute and interpret the variance of ``actual`` against ``planned``.

    Both values are validated against the metric first. Direction semantics
    (docs/07-PROGRESS-FEEDBACK.md "Variance"):
    maximize — actual ≥ planned is favorable; minimize — actual ≤ planned;
    target — actual == planned.
    """
    if not isinstance(metric, Metric):
        raise MetricError("metric must be a Metric")
    planned = metric.validate(planned)
    actual = metric.validate(actual)
    delta = _numeric(actual) - _numeric(planned)
    if metric.direction is MetricDirection.MAXIMIZE:
        favorable = delta >= 0
    elif metric.direction is MetricDirection.MINIMIZE:
        favorable = delta <= 0
    else:  # TARGET
        favorable = delta == 0
    return Variance(metric=metric, planned=planned, actual=actual, delta=delta, favorable=favorable)
