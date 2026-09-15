"""Tests for gap calculation (TASK-021).

calculate_gap is the deterministic backcasting step 4: it refuses
incoherent contexts (ownership mismatch, target not after snapshot) via
the cross-entity validator, builds validated dimensions from
(metric, current, target) triples, and records the gap.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import Gap, GapDimension, GapError, calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.metric import Metric, MetricDirection, MetricKind
from backcasting.domain.validation import DomainValidationError

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
CALCULATED = datetime(2026, 1, 6, tzinfo=timezone.utc)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)

DISTANCE = Metric("Distance", MetricKind.COUNT, MetricDirection.MAXIMIZE)
RUNS = Metric("Weekly runs", MetricKind.COUNT, MetricDirection.MAXIMIZE)
WEIGHT = Metric("Weight", MetricKind.COUNT, MetricDirection.TARGET, target_value=70)


@pytest.fixture
def context():
    goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
    current = capture_current_state(
        goal.goal_id, "Can run 5 km.", captured_at=CAPTURED
    )
    future = define_future_state(
        goal.goal_id, "Complete the marathon.", TARGET, created_at=CREATED
    )
    return goal, current, future


class TestCalculateGap:
    def test_calculates_gap_with_dimensions(self, context) -> None:
        goal, current, future = context
        gap = calculate_gap(
            goal,
            current,
            future,
            (
                (DISTANCE, 5, 42),
                (RUNS, 2, 5),
            ),
            narrative="Base endurance is missing.",
            calculated_at=CALCULATED,
        )
        assert isinstance(gap, Gap)
        assert gap.goal_id == goal.goal_id
        assert gap.current_state_id == current.state_id
        assert gap.future_state_id == future.state_id
        assert gap.calculated_at == CALCULATED
        assert gap.narrative == "Base endurance is missing."
        assert [d.metric.name for d in gap.dimensions] == ["Distance", "Weekly runs"]
        assert gap.dimensions[0].current_value == 5
        assert gap.dimensions[0].target_value == 42

    def test_gap_without_measurements_is_qualitative(self, context) -> None:
        goal, current, future = context
        gap = calculate_gap(goal, current, future, calculated_at=CALCULATED)
        assert gap.dimensions == ()
        assert gap.narrative == ""

    def test_target_metric_uses_supplied_target(self, context) -> None:
        goal, current, future = context
        gap = calculate_gap(
            goal, current, future, ((WEIGHT, 78, 70),), calculated_at=CALCULATED
        )
        assert gap.dimensions[0].current_value == 78
        assert gap.dimensions[0].target_value == 70

    def test_generates_identity_and_timestamp_by_default(self, context) -> None:
        goal, current, future = context
        before = datetime.now(timezone.utc)
        gap = calculate_gap(goal, current, future)
        after = datetime.now(timezone.utc)
        assert isinstance(gap.gap_id, uuid.UUID)
        assert before <= gap.calculated_at <= after

    def test_injected_identity_is_honoured(self, context) -> None:
        goal, current, future = context
        gap_id = uuid.uuid4()
        gap = calculate_gap(
            goal, current, future, gap_id=gap_id, calculated_at=CALCULATED
        )
        assert gap.gap_id == gap_id

    def test_mismatched_future_state_is_refused(self, context) -> None:
        goal, current, _ = context
        other_future = define_future_state(
            uuid.uuid4(), "Other goal.", TARGET, created_at=CREATED
        )
        with pytest.raises(DomainValidationError):
            calculate_gap(goal, current, other_future, calculated_at=CALCULATED)

    def test_mismatched_current_state_is_refused(self, context) -> None:
        goal, _, future = context
        other_current = capture_current_state(
            uuid.uuid4(), "Other reality.", captured_at=CAPTURED
        )
        with pytest.raises(DomainValidationError):
            calculate_gap(goal, other_current, future, calculated_at=CALCULATED)

    def test_target_not_after_snapshot_is_refused(self, context) -> None:
        goal, _, future = context
        later = capture_current_state(
            goal.goal_id, "Later reality.", captured_at=TARGET + timedelta(days=1)
        )
        with pytest.raises(DomainValidationError):
            calculate_gap(goal, later, future, calculated_at=CALCULATED)

    def test_invalid_measurement_values_are_refused(self, context) -> None:
        goal, current, future = context
        with pytest.raises(GapError):
            calculate_gap(
                goal, current, future, ((DISTANCE, -5, 42),), calculated_at=CALCULATED
            )
        with pytest.raises(GapError):
            calculate_gap(
                goal, current, future, ((DISTANCE, 5, "42"),), calculated_at=CALCULATED
            )

    def test_duplicate_metrics_are_refused(self, context) -> None:
        goal, current, future = context
        with pytest.raises(GapError):
            calculate_gap(
                goal,
                current,
                future,
                ((DISTANCE, 5, 42), (DISTANCE, 6, 42)),
                calculated_at=CALCULATED,
            )

    @pytest.mark.parametrize(
        "make_bad",
        [
            lambda g, c, f: calculate_gap("goal", c, f),  # type: ignore[arg-type]
            lambda g, c, f: calculate_gap(g, "current", f),  # type: ignore[arg-type]
            lambda g, c, f: calculate_gap(g, c, "future"),  # type: ignore[arg-type]
        ],
    )
    def test_wrong_types_raise_type_error(self, context, make_bad) -> None:
        goal, current, future = context
        with pytest.raises(TypeError):
            make_bad(goal, current, future)
