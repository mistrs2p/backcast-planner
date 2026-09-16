"""Tests for thresholds (TASK-080).

The magnitude bounds of docs/08's stability controls: how far a
reading must slip before it is trigger-worthy, and (hysteresis)
how far it must recover before it clears.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from backcasting.domain.availability import create_availability_window
from backcasting.domain.calendar import create_calendar
from backcasting.domain.execution import create_execution
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.progress import take_progress_snapshot
from backcasting.domain.sustainability import assess_sustainability
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.threshold import (
    Measure,
    Threshold,
    ThresholdError,
    completion_shortfall,
    utilization,
    variance_shortfall,
)
from backcasting.domain.velocity import compute_velocity
from backcasting.domain.variance import progress_variance, time_variance

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)
MONDAYS = frozenset({0})  # one workday per week, for readable ratios


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, hours=None):
    task = create_task(plan, "Task", created_at=CREATED)
    if hours is not None:
        task = revise_task(task, duration=timedelta(hours=hours), updated_at=CREATED)
    return task


def _sitting(task, day, start_hour, end_hour):
    day = day.replace(hour=start_hour)
    return create_execution(task, day, day.replace(hour=end_hour), created_at=CREATED)


class TestThresholdRecord:
    def test_plain_threshold_defaults_exit_to_enter(self) -> None:
        threshold = Threshold(Measure.SHORTFALL, 4 * HOUR)
        assert threshold.enter_bound == 4 * HOUR
        assert threshold.exit_bound == 4 * HOUR

    def test_hysteresis_holds_both_bounds(self) -> None:
        threshold = Threshold(Measure.SHORTFALL, 4 * HOUR, 2 * HOUR)
        assert threshold.enter_bound == 4 * HOUR
        assert threshold.exit_bound == 2 * HOUR

    def test_equal_bounds_are_allowed(self) -> None:
        Threshold(Measure.SHORTFALL, 4 * HOUR, 4 * HOUR)

    def test_rate_measures_take_numbers(self) -> None:
        threshold = Threshold(Measure.UTILIZATION, 0.8, 0.6)
        assert threshold.enter_bound == 0.8
        assert threshold.exit_bound == 0.6

    def test_duration_measure_rejects_numbers(self) -> None:
        with pytest.raises(ThresholdError, match="non-negative timedelta"):
            Threshold(Measure.SHORTFALL, 4)

    def test_rate_measures_reject_timedeltas(self) -> None:
        with pytest.raises(ThresholdError, match="non-negative number"):
            Threshold(Measure.UTILIZATION, 8 * HOUR)

    def test_rejects_negative_bounds(self) -> None:
        with pytest.raises(ThresholdError, match="non-negative timedelta"):
            Threshold(Measure.SHORTFALL, -HOUR)
        with pytest.raises(ThresholdError, match="non-negative number"):
            Threshold(Measure.UTILIZATION, -0.1)

    def test_rejects_bool_bounds(self) -> None:
        with pytest.raises(ThresholdError, match="non-negative number"):
            Threshold(Measure.UTILIZATION, True)

    def test_exit_must_not_exceed_enter(self) -> None:
        with pytest.raises(ThresholdError, match="exit_bound must not exceed"):
            Threshold(Measure.SHORTFALL, 2 * HOUR, 4 * HOUR)
        with pytest.raises(ThresholdError, match="exit_bound must not exceed"):
            Threshold(Measure.UTILIZATION, 0.6, 0.8)

    def test_rejects_bad_measure(self) -> None:
        with pytest.raises(ThresholdError, match="measure must be"):
            Threshold("shortfall", 4 * HOUR)  # type: ignore[arg-type]

    def test_is_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        threshold = Threshold(Measure.SHORTFALL, 4 * HOUR)
        with pytest.raises(FrozenInstanceError):
            threshold.enter_bound = 2 * HOUR  # type: ignore[misc]


class TestEvaluation:
    def test_exceeded_at_and_beyond_the_enter_bound(self) -> None:
        threshold = Threshold(Measure.SHORTFALL, 4 * HOUR)
        assert not threshold.is_exceeded(3 * HOUR + timedelta(minutes=59))
        assert threshold.is_exceeded(4 * HOUR)
        assert threshold.is_exceeded(5 * HOUR)

    def test_cleared_at_and_below_the_exit_bound(self) -> None:
        threshold = Threshold(Measure.SHORTFALL, 4 * HOUR, 2 * HOUR)
        assert threshold.has_cleared(2 * HOUR)
        assert threshold.has_cleared(HOUR)
        assert not threshold.has_cleared(3 * HOUR)

    def test_hysteresis_does_not_flap_in_the_gap(self) -> None:
        """The whole point: between the bounds, neither exceeded nor
        cleared — the condition holds whatever state it had."""
        threshold = Threshold(Measure.SHORTFALL, 4 * HOUR, 2 * HOUR)
        hovering = 3 * HOUR
        assert not threshold.is_exceeded(hovering)
        assert not threshold.has_cleared(hovering)

    def test_enter_wins_on_equal_bounds(self) -> None:
        threshold = Threshold(Measure.SHORTFALL, 4 * HOUR)
        exactly = 4 * HOUR
        assert threshold.is_exceeded(exactly)
        assert threshold.has_cleared(exactly)

    def test_rate_evaluation(self) -> None:
        threshold = Threshold(Measure.UTILIZATION, 0.8)
        assert threshold.is_exceeded(0.9)
        assert not threshold.is_exceeded(0.7)

    def test_zero_bound_is_entered_by_zero_magnitude(self) -> None:
        threshold = Threshold(Measure.SHORTFALL, timedelta(0))
        assert threshold.is_exceeded(timedelta(0))

    def test_rejects_wrong_magnitude_types(self) -> None:
        duration = Threshold(Measure.SHORTFALL, 4 * HOUR)
        with pytest.raises(ThresholdError, match="magnitude must be"):
            duration.is_exceeded(4)
        rate = Threshold(Measure.UTILIZATION, 0.8)
        with pytest.raises(ThresholdError, match="magnitude must be"):
            rate.is_exceeded(4 * HOUR)
        with pytest.raises(ThresholdError, match="magnitude must be"):
            rate.is_exceeded(-0.1)
        with pytest.raises(ThresholdError, match="magnitude must be"):
            duration.has_cleared(-HOUR)


class TestVarianceShortfall:
    def _snapshot(self, plan, task, executions):
        return take_progress_snapshot(
            plan, (task,), executions, at=MONDAY + timedelta(days=1)
        )

    def test_unfavorable_progress_variance_is_the_shortfall(self, plan) -> None:
        task = _task(plan, 4)
        executions = (_sitting(task, MONDAY, 9, 11),)  # 2h of a 4h estimate
        snapshot = self._snapshot(plan, task, executions)
        variance = progress_variance(snapshot)
        assert not variance.favorable
        assert variance_shortfall(variance) == 2 * HOUR

    def test_favorable_variance_contributes_zero(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = self._snapshot(plan, task, (_sitting(task, MONDAY, 9, 13),))
        variance = progress_variance(snapshot)
        assert variance.favorable
        assert variance_shortfall(variance) == timedelta(0)

    def test_time_overrun_is_a_shortfall(self, plan) -> None:
        """An unfavorable time variance overran its estimate; the
        overrun is the slip a threshold weighs."""
        task = _task(plan, 4)
        executions = (_sitting(task, MONDAY, 9, 15),)  # 6h of a 4h estimate
        variance = time_variance(task, executions)
        assert not variance.favorable
        assert variance_shortfall(variance) == 2 * HOUR

    def test_rejects_non_variance(self) -> None:
        with pytest.raises(ThresholdError, match="variance must be"):
            variance_shortfall("behind")  # type: ignore[arg-type]


class TestUtilization:
    def test_reading_utilization_passes_through(self, plan) -> None:
        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        window = create_availability_window(
            calendar, MONDAYS, time(9), time(17), created_at=CREATED
        )
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 9, 13),)  # half the window
        velocity = compute_velocity(executions, at=MONDAY + WEEK, window=WEEK)
        reading = assess_sustainability(velocity, (window,))
        assert utilization(reading) == 0.5

    def test_no_workable_time_contributes_zero(self) -> None:
        velocity = compute_velocity((), at=MONDAY + WEEK, window=WEEK)
        reading = assess_sustainability(velocity, ())
        assert reading.utilization is None
        assert utilization(reading) == 0.0

    def test_rejects_non_reading(self) -> None:
        with pytest.raises(ThresholdError, match="reading must be"):
            utilization("busy")  # type: ignore[arg-type]


class TestCompletionShortfall:
    def test_unfinished_share(self, plan) -> None:
        task = _task(plan, 4)
        executions = (_sitting(task, MONDAY, 9, 13),)  # one of two tasks done
        other = _task(plan, 4)
        snapshot = take_progress_snapshot(
            plan, (task, other), executions, at=MONDAY + timedelta(days=1)
        )
        assert snapshot.completion_rate == 0.5
        assert completion_shortfall(snapshot) == 0.5

    def test_complete_plan_has_no_shortfall(self, plan) -> None:
        task = _task(plan, 4)
        executions = (_sitting(task, MONDAY, 9, 13),)
        snapshot = take_progress_snapshot(
            plan, (task,), executions, at=MONDAY + timedelta(days=1)
        )
        assert completion_shortfall(snapshot) == 0.0

    def test_rejects_non_snapshot(self) -> None:
        with pytest.raises(ThresholdError, match="snapshot must be"):
            completion_shortfall("half done")  # type: ignore[arg-type]


class TestWiring:
    def test_readings_reduce_to_magnitudes_and_cross_thresholds(self, plan) -> None:
        """The chain: records → signals → slip magnitudes → threshold
        crossings — the input TASK-081's persistence will count."""
        from backcasting.domain.trigger import TriggerKind, raise_trigger

        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        window = create_availability_window(
            calendar, MONDAYS, time(9), time(17), created_at=CREATED
        )
        task = _task(plan, 12)
        # 8h worked of a 12h task, half inside the window, half in an
        # evening sprint past it.
        executions = (
            _sitting(task, MONDAY, 9, 13),
            _sitting(task, MONDAY, 19, 23),
        )
        at = MONDAY + WEEK

        snapshot = take_progress_snapshot(plan, (task,), executions, at=at)
        behind = progress_variance(snapshot)
        velocity = compute_velocity(executions, at=at, window=WEEK)
        reading = assess_sustainability(velocity, (window,))

        slip = variance_shortfall(behind)
        load = utilization(reading)
        unfinished = completion_shortfall(snapshot)
        assert slip == 4 * HOUR
        assert load == 1.0
        assert unfinished == 1.0

        hours = Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)
        ceiling = Threshold(Measure.UTILIZATION, 0.8)
        completion = Threshold(Measure.COMPLETION, 0.25)

        assert hours.is_exceeded(slip)
        assert ceiling.is_exceeded(load)
        assert completion.is_exceeded(unfinished)

        triggers = (
            raise_trigger(
                TriggerKind.PROGRESS, f"{slip} behind plan.", observed_at=at
            ),
            raise_trigger(
                TriggerKind.CAPACITY,
                f"Utilization {load:.2f} over the ceiling.",
                observed_at=at,
            ),
        )
        assert all(t.kind in {TriggerKind.PROGRESS, TriggerKind.CAPACITY} for t in triggers)

    def test_recovery_clears_through_hysteresis(self, plan) -> None:
        """Week two's work closes the gap: the slip falls through the
        exit bound, and the condition clears."""
        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        window = create_availability_window(
            calendar, MONDAYS, time(9), time(17), created_at=CREATED
        )
        task = _task(plan, 8)
        week_one = (_sitting(task, MONDAY, 9, 13),)  # 4h of 8h: 4h behind
        week_two = (
            _sitting(task, MONDAY, 9, 13),
            _sitting(task, MONDAY + timedelta(days=7), 9, 11),
            _sitting(task, MONDAY + timedelta(days=7), 14, 16),
        )
        hours = Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)

        first = variance_shortfall(
            progress_variance(
                take_progress_snapshot(plan, (task,), week_one, at=MONDAY + WEEK)
            )
        )
        second = variance_shortfall(
            progress_variance(
                take_progress_snapshot(
                    plan, (task,), week_two, at=MONDAY + 2 * WEEK
                )
            )
        )
        assert hours.is_exceeded(first)
        assert not hours.has_cleared(first)
        assert second == timedelta(0)
        assert hours.has_cleared(second)
