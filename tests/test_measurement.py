"""Tests for the measurement model (TASK-070).

A Measurement is the observation half of docs/02's "Measurement:
observed data" — one validly-typed value of a Metric (TASK-015), at
one moment, about one subject; immutable, with corrections arriving
as new records.
"""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.backcasting_run import start_run
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.measurement import (
    Measurement,
    MeasurementError,
    latest_measurement,
    measurements_for_subject,
    record_measurement,
)
from backcasting.domain.metric import (
    Metric,
    MetricDirection,
    MetricError,
    MetricKind,
    interpret_variance,
)
from backcasting.domain.repositories import MeasurementRepository

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
CALCULATED = datetime(2026, 1, 6, tzinfo=timezone.utc)
STARTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
TARGET_DATE = datetime(2026, 10, 11, tzinfo=timezone.utc)
CHECKPOINT = datetime(2026, 6, 1, tzinfo=timezone.utc)
MEASURED = datetime(2026, 6, 2, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)

PERCENT_DONE = Metric(
    "Course completion", MetricKind.PERCENTAGE, MetricDirection.MAXIMIZE
)
SESSIONS = Metric("Study sessions", MetricKind.COUNT, MetricDirection.MAXIMIZE)
STUDIED = Metric("Time studied", MetricKind.DURATION, MetricDirection.MAXIMIZE)
PASSED = Metric("Exam passed", MetricKind.BOOLEAN, MetricDirection.MAXIMIZE)
MOOD = Metric(
    "Session mood",
    MetricKind.SCORE,
    MetricDirection.MAXIMIZE,
    score_min=1,
    score_max=5,
)
ON_TARGET = Metric(
    "Weekly hours", MetricKind.DURATION, MetricDirection.TARGET, target_value=10 * HOUR
)


class TestMeasurement:
    def test_record_shape(self) -> None:
        measurement = record_measurement(
            PERCENT_DONE, 42, measured_at=MEASURED
        )
        assert isinstance(measurement.measurement_id, uuid.UUID)
        assert measurement.metric == PERCENT_DONE
        assert measurement.value == 42
        assert measurement.measured_at == MEASURED
        assert measurement.subject_id is None

    def test_value_types_follow_the_metric_kind(self) -> None:
        assert record_measurement(STUDIED, 2 * HOUR, measured_at=MEASURED).value == 2 * HOUR
        assert record_measurement(PASSED, False, measured_at=MEASURED).value is False
        assert record_measurement(MOOD, 4, measured_at=MEASURED).value == 4
        assert record_measurement(SESSIONS, 3, measured_at=MEASURED).value == 3

    def test_injectable_id_and_clock(self) -> None:
        measurement_id = uuid.uuid4()
        measurement = record_measurement(
            PERCENT_DONE,
            42,
            subject_id=uuid.uuid4(),
            measurement_id=measurement_id,
            measured_at=MEASURED,
        )
        assert measurement.measurement_id == measurement_id
        assert measurement.subject_id is not None

    def test_is_immutable(self) -> None:
        measurement = record_measurement(PERCENT_DONE, 42, measured_at=MEASURED)
        with pytest.raises(FrozenInstanceError):
            measurement.value = 43  # type: ignore[misc]

    def test_rejects_values_outside_the_metric_kind(self) -> None:
        with pytest.raises(MetricError, match="count value must be an integer"):
            record_measurement(SESSIONS, "many", measured_at=MEASURED)
        with pytest.raises(MetricError, match="percentage value must be within"):
            record_measurement(PERCENT_DONE, 142, measured_at=MEASURED)
        with pytest.raises(MetricError, match="boolean value must be a bool"):
            record_measurement(PASSED, "yes", measured_at=MEASURED)

    def test_rejects_values_outside_the_score_scale(self) -> None:
        with pytest.raises(MetricError, match="score value must be within"):
            record_measurement(MOOD, 9, measured_at=MEASURED)

    def test_rejects_naive_measured_at(self) -> None:
        with pytest.raises(MeasurementError, match="measured_at must be"):
            record_measurement(PERCENT_DONE, 42, measured_at=datetime(2026, 6, 2))

    def test_rejects_non_utc_measured_at(self) -> None:
        from zoneinfo import ZoneInfo

        tokyo = MEASURED.astimezone(ZoneInfo("Asia/Tokyo"))
        with pytest.raises(MeasurementError, match="measured_at must be in UTC"):
            record_measurement(PERCENT_DONE, 42, measured_at=tokyo)

    def test_rejects_bad_subject_id(self) -> None:
        with pytest.raises(MeasurementError, match="subject_id must be a UUID"):
            record_measurement(PERCENT_DONE, 42, subject_id="milestone", measured_at=MEASURED)

    def test_rejects_non_metric(self) -> None:
        with pytest.raises(TypeError, match="metric must be a Metric"):
            record_measurement("percent done", 42, measured_at=MEASURED)

    def test_direct_construction_validates_like_the_factory(self) -> None:
        with pytest.raises(MeasurementError, match="metric must be a Metric"):
            Measurement(
                measurement_id=uuid.uuid4(),
                metric="percent done",
                value=42,
                measured_at=MEASURED,
            )
        with pytest.raises(MetricError, match="duration value must be a timedelta"):
            Measurement(
                measurement_id=uuid.uuid4(),
                metric=STUDIED,
                value="2 hours",
                measured_at=MEASURED,
            )


class TestMeasurementsForSubject:
    def test_filters_by_subject_keeping_input_order(self) -> None:
        subject = uuid.uuid4()
        other = uuid.uuid4()
        first = record_measurement(PERCENT_DONE, 10, subject_id=subject, measured_at=MEASURED)
        elsewhere = record_measurement(PERCENT_DONE, 20, subject_id=other, measured_at=MEASURED)
        second = record_measurement(SESSIONS, 1, subject_id=subject, measured_at=MEASURED + HOUR)
        assert measurements_for_subject((first, elsewhere, second), subject) == (first, second)

    def test_subjectless_measurements_are_not_matched(self) -> None:
        floating = record_measurement(PERCENT_DONE, 10, measured_at=MEASURED)
        assert measurements_for_subject((floating,), uuid.uuid4()) == ()

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(MeasurementError, match="subject_id must be a UUID"):
            measurements_for_subject((), "subject")
        with pytest.raises(MeasurementError, match="measurements must be a tuple"):
            measurements_for_subject([], uuid.uuid4())
        with pytest.raises(MeasurementError, match="Measurement instances"):
            measurements_for_subject(("x",), uuid.uuid4())


class TestLatestMeasurement:
    def test_picks_the_most_recent(self) -> None:
        older = record_measurement(PERCENT_DONE, 10, measured_at=MEASURED)
        newer = record_measurement(PERCENT_DONE, 25, measured_at=MEASURED + 3 * HOUR)
        assert latest_measurement((older, newer)) is newer

    def test_input_order_does_not_matter(self) -> None:
        older = record_measurement(PERCENT_DONE, 10, measured_at=MEASURED)
        newer = record_measurement(PERCENT_DONE, 25, measured_at=MEASURED + 3 * HOUR)
        assert latest_measurement((newer, older)) is newer

    def test_ties_resolve_to_the_last_in_input_order(self) -> None:
        first = record_measurement(PERCENT_DONE, 10, measured_at=MEASURED)
        second = record_measurement(PERCENT_DONE, 20, measured_at=MEASURED)
        assert latest_measurement((first, second)) is second

    def test_empty_returns_none(self) -> None:
        assert latest_measurement(()) is None

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(MeasurementError, match="measurements must be a tuple"):
            latest_measurement([])
        with pytest.raises(MeasurementError, match="Measurement instances"):
            latest_measurement(("x",))


class TestMeasurementRepositoryPort:
    def test_in_memory_fake_honours_the_contract(self) -> None:
        repo = InMemoryMeasurementRepository()
        subject = uuid.uuid4()
        early = record_measurement(
            PERCENT_DONE, 10, subject_id=subject, measured_at=MEASURED + HOUR
        )
        late = record_measurement(
            PERCENT_DONE, 30, subject_id=subject, measured_at=MEASURED
        )
        elsewhere = record_measurement(
            PERCENT_DONE, 99, subject_id=uuid.uuid4(), measured_at=MEASURED
        )
        for measurement in (early, late, elsewhere):
            repo.save(measurement)
        assert repo.get(late.measurement_id) is late
        assert repo.get(uuid.uuid4()) is None
        assert repo.list_for_subject(subject) == (late, early)

    def test_port_shape(self) -> None:
        assert {"save", "get", "list_for_subject"} <= set(
            MeasurementRepository.__abstractmethods__
        )


class InMemoryMeasurementRepository(MeasurementRepository):
    """The reference fake: a dict keyed by id, per-subject listing."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Measurement] = {}

    def save(self, measurement: Measurement) -> None:
        self._by_id[measurement.measurement_id] = measurement

    def get(self, measurement_id: uuid.UUID) -> Measurement | None:
        return self._by_id.get(measurement_id)

    def list_for_subject(self, subject_id: uuid.UUID) -> tuple[Measurement, ...]:
        return tuple(
            sorted(
                (
                    m
                    for m in self._by_id.values()
                    if m.subject_id == subject_id
                ),
                key=lambda m: m.measured_at,
            )
        )


class TestWiring:
    @pytest.fixture
    def running_run(self):
        goal = create_goal(uuid.uuid4(), "Pass the exam", created_at=CREATED)
        current = capture_current_state(
            goal.goal_id, "60% of the course completed.", captured_at=CAPTURED
        )
        future = define_future_state(
            goal.goal_id, "Course complete, exam passed.", TARGET_DATE, created_at=CREATED
        )
        gap = calculate_gap(goal, current, future, calculated_at=CALCULATED)
        return start_run(goal, current, future, gap, started_at=STARTED)

    def test_milestones_and_outcomes_become_measurable(self, running_run) -> None:
        """docs/02: a milestone is an "intermediate measurable
        checkpoint" — measurability arrives by observing it."""
        from backcasting.domain.milestone import define_milestone
        from backcasting.domain.outcome import define_outcome
        from backcasting.domain.plan import create_plan

        goal = create_goal(uuid.uuid4(), "Pass the exam", created_at=CREATED)
        plan = create_plan(goal, 10 * HOUR, created_at=CREATED)
        milestone = define_milestone(
            running_run, "Halfway through the course", CHECKPOINT, created_at=STARTED
        )
        outcome = define_outcome(
            plan, "Course completed", milestone=milestone, created_at=CREATED
        )

        readings = (
            record_measurement(
                PERCENT_DONE, 40, subject_id=milestone.milestone_id, measured_at=MEASURED
            ),
            record_measurement(
                PERCENT_DONE,
                55,
                subject_id=milestone.milestone_id,
                measured_at=MEASURED + timedelta(days=7),
            ),
            record_measurement(
                PASSED, True, subject_id=outcome.outcome_id, measured_at=MEASURED + timedelta(days=30)
            ),
        )
        milestone_readings = measurements_for_subject(readings, milestone.milestone_id)
        assert len(milestone_readings) == 2
        assert latest_measurement(milestone_readings).value == 55
        assert (
            latest_measurement(measurements_for_subject(readings, outcome.outcome_id)).value
            is True
        )

    def test_measurement_feeds_variance_interpretation(self) -> None:
        """The observation is the Actual of docs/07's variance; the
        metric's target supplies the planned side."""
        observation = record_measurement(
            ON_TARGET, 8 * HOUR, measured_at=MEASURED
        )
        variance = interpret_variance(
            observation.metric,
            observation.metric.target_value,
            observation.value,
        )
        assert variance.delta == -2 * HOUR.total_seconds()
        assert variance.favorable is False

    def test_correction_arrives_as_a_new_record(self) -> None:
        """No revision path: the corrected reading is a new immutable
        fact, and `latest` picks it up by time, not by mutation."""
        wrong = record_measurement(PERCENT_DONE, 45, measured_at=MEASURED)
        corrected = record_measurement(
            PERCENT_DONE, 54, measured_at=MEASURED + timedelta(minutes=5)
        )
        assert wrong.value == 45  # history is not rewritten
        assert latest_measurement((wrong, corrected)) is corrected
