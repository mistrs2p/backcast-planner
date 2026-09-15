"""Measurement — observed data for a metric.

"Measurement: observed data" (docs/02-CONCEPTUAL-MODEL.md, Adaptation
Layer). A :class:`~backcasting.domain.metric.Metric` (TASK-015) is the
*definition* — a named, typed way of measuring; a Measurement is the
*observation* — one value of that metric, taken at one moment, about
one subject. The two only meet here: "Milestone: intermediate
measurable checkpoint" (docs/02) means a milestone becomes measurable
by having measurements taken against it (same for an Outcome).

The invariants follow from "observed data" and the
"Planned ≠ Actual ≠ Progress" rule (docs/07-PROGRESS-FEEDBACK.md):

- the value is validated against the metric's kind (and scale) — an
  observation outside its metric's type is a recording error, not a
  deviation to interpret;
- ``measured_at`` is when the observation was taken (default: now),
  which may be any time — unlike ObservedCapacity there is no period
  being summarized, so nothing can be "not yet observable";
- like every measurement in this domain (see
  :mod:`~backcasting.domain.observed_capacity`), a Measurement is an
  immutable fact of history: no ``updated_at``, no revision path — a
  corrected measurement is a new record. This is what makes the
  planned/actual comparison (variance, docs/07) meaningful.

The link to the measured subject is an optional ``subject_id`` (the
milestone or outcome being observed): docs/03-DOMAIN-MODEL.md fixes
the Milestone/Outcome shapes without a metric association, so the
association lives on the measurement side — a subject with no
measurements is simply not yet measured, and a measurement with no
subject is a free-standing observation of the metric itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from backcasting.domain.metric import Metric
from backcasting.domain.timezone import UTC, require_utc


class MeasurementError(ValueError):
    """Raised when a measurement invariant is violated."""


@dataclass(frozen=True)
class Measurement:
    """One observed value of a metric, taken at one moment.

    The metric is held by value, as :class:`~backcasting.domain.metric.Variance`
    holds it: the definition as it stood when the observation was made is
    part of the fact (a metric whose scale later changes does not rewrite
    history).
    """

    measurement_id: uuid.UUID
    metric: Metric
    value: object
    measured_at: datetime
    subject_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.measurement_id, uuid.UUID):
            raise MeasurementError("measurement_id must be a UUID")
        if not isinstance(self.metric, Metric):
            raise MeasurementError("metric must be a Metric")
        require_utc("measured_at", self.measured_at, error=MeasurementError)
        if self.subject_id is not None and not isinstance(self.subject_id, uuid.UUID):
            raise MeasurementError("subject_id must be a UUID or None")
        self.metric.validate(self.value)


def record_measurement(
    metric: Metric,
    value: object,
    *,
    subject_id: uuid.UUID | None = None,
    measurement_id: uuid.UUID | None = None,
    measured_at: datetime | None = None,
) -> Measurement:
    """Record one observation of ``metric``.

    ``value`` is validated against the metric's kind (and scale); the
    observation is stamped at ``measured_at`` (default: now). An
    out-of-type value is refused — it is a recording error, not a
    deviation; deviations are the variance layer's material
    (docs/07-PROGRESS-FEEDBACK.md), and they only exist between
    validly-recorded values.
    """
    if not isinstance(metric, Metric):
        raise TypeError("metric must be a Metric")
    value = metric.validate(value)
    if subject_id is not None and not isinstance(subject_id, uuid.UUID):
        raise MeasurementError("subject_id must be a UUID or None")
    return Measurement(
        measurement_id=measurement_id if measurement_id is not None else uuid.uuid4(),
        metric=metric,
        value=value,
        measured_at=measured_at if measured_at is not None else datetime.now(UTC),
        subject_id=subject_id,
    )


def measurements_for_subject(
    measurements: tuple[Measurement, ...],
    subject_id: uuid.UUID,
) -> tuple[Measurement, ...]:
    """The observations taken about one subject, in input order."""
    if not isinstance(subject_id, uuid.UUID):
        raise MeasurementError("subject_id must be a UUID")
    if not isinstance(measurements, tuple):
        raise MeasurementError("measurements must be a tuple of Measurement")
    for measurement in measurements:
        if not isinstance(measurement, Measurement):
            raise MeasurementError("measurements must be Measurement instances")
    return tuple(
        measurement for measurement in measurements
        if measurement.subject_id == subject_id
    )


def latest_measurement(
    measurements: tuple[Measurement, ...],
) -> Measurement | None:
    """The most recent observation, or ``None`` when there is none.

    Ties on ``measured_at`` resolve to the last in input order: when
    two observations claim the same instant, the later-recorded one is
    the more current reading. The empty case is ``None`` — an absence,
    not an error.
    """
    if not isinstance(measurements, tuple):
        raise MeasurementError("measurements must be a tuple of Measurement")
    for measurement in measurements:
        if not isinstance(measurement, Measurement):
            raise MeasurementError("measurements must be Measurement instances")
    latest: Measurement | None = None
    for measurement in measurements:
        if latest is None or measurement.measured_at >= latest.measured_at:
            latest = measurement
    return latest
