"""Tests for trend analysis (TASK-074).

Pace direction across consecutive velocity windows (strict
comparison, no fuzz band) and the completion projection that turns a
pace and a remaining workload into a date.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.execution import create_execution
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.progress import take_progress_snapshot
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.trend import (
    Trend,
    TrendDirection,
    TrendError,
    analyze_trend,
    project_completion,
)
from backcasting.domain.velocity import compute_velocity

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
WEEK = timedelta(days=7)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, hours):
    task = create_task(plan, "Task", created_at=CREATED)
    return revise_task(task, duration=timedelta(hours=hours), updated_at=CREATED)


def _sitting(task, day, start_hour, end_hour):
    day = day.replace(hour=start_hour)
    return create_execution(task, day, day.replace(hour=end_hour), created_at=CREATED)


def _windows(executions, *, at, window, count):
    """Consecutive velocity windows ending at ``at``, oldest first."""
    return tuple(
        compute_velocity(executions, at=at - i * window, window=window)
        for i in reversed(range(count))
    )


class TestAnalyzeTrend:
    def test_accelerating(self, plan) -> None:
        task = _task(plan, 40)
        executions = (
            _sitting(task, MONDAY, 9, 11),              # previous week: 2h
            _sitting(task, MONDAY + 8 * DAY, 9, 17),    # recent week: 8h
        )
        at = MONDAY + 14 * DAY
        trend = analyze_trend(_windows(executions, at=at, window=WEEK, count=2))
        assert trend.direction is TrendDirection.ACCELERATING

    def test_decelerating(self, plan) -> None:
        task = _task(plan, 40)
        executions = (
            _sitting(task, MONDAY, 9, 17),              # previous week: 8h
            _sitting(task, MONDAY + 8 * DAY, 9, 11),    # recent week: 2h
        )
        at = MONDAY + 14 * DAY
        trend = analyze_trend(_windows(executions, at=at, window=WEEK, count=2))
        assert trend.direction is TrendDirection.DECELERATING

    def test_steady(self, plan) -> None:
        task = _task(plan, 40)
        executions = (
            _sitting(task, MONDAY, 9, 13),
            _sitting(task, MONDAY + 8 * DAY, 9, 13),
        )
        at = MONDAY + 14 * DAY
        trend = analyze_trend(_windows(executions, at=at, window=WEEK, count=2))
        assert trend.direction is TrendDirection.STEADY

    def test_the_last_two_windows_decide(self, plan) -> None:
        """Earlier history is context; the trend reads the latest pair."""
        task = _task(plan, 40)
        executions = (
            _sitting(task, MONDAY - 14 * DAY, 9, 17),   # ancient, ignored
            _sitting(task, MONDAY, 9, 11),              # previous: 2h
            _sitting(task, MONDAY + 8 * DAY, 9, 15),    # recent: 6h
        )
        at = MONDAY + 14 * DAY
        trend = analyze_trend(_windows(executions, at=at, window=WEEK, count=3))
        assert trend.direction is TrendDirection.ACCELERATING
        assert trend.recent.worked == 6 * HOUR
        assert trend.previous.worked == 2 * HOUR

    def test_window_bounds_are_exposed(self, plan) -> None:
        task = _task(plan, 40)
        at = MONDAY + 14 * DAY
        trend = analyze_trend(
            _windows((), at=at, window=WEEK, count=2)
        )
        assert trend.previous.window_end == trend.recent.window_start
        assert trend.recent.window_end == at

    def test_needs_two_windows(self) -> None:
        with pytest.raises(TrendError, match="at least two windows"):
            analyze_trend(())
        only = compute_velocity((), at=MONDAY, window=WEEK)
        with pytest.raises(TrendError, match="at least two windows"):
            analyze_trend((only,))

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(TrendError, match="velocities must be a tuple"):
            analyze_trend([])
        with pytest.raises(TrendError, match="Velocity instances"):
            analyze_trend(("x", "y"))


class TestTrendRecord:
    def _velocities(self, worked_recent=8 * HOUR, worked_previous=2 * HOUR):
        recent = compute_velocity((), at=MONDAY + WEEK, window=WEEK)
        previous = compute_velocity((), at=MONDAY, window=WEEK)
        from dataclasses import replace

        return (
            replace(recent, worked=worked_recent, rate=worked_recent / WEEK),
            replace(previous, worked=worked_previous, rate=worked_previous / WEEK),
        )

    def test_valid_construction(self) -> None:
        recent, previous = self._velocities()
        trend = Trend(TrendDirection.ACCELERATING, recent, previous)
        assert trend.recent is recent

    def test_windows_must_be_consecutive(self) -> None:
        recent = compute_velocity((), at=MONDAY + 2 * WEEK, window=WEEK)
        previous = compute_velocity((), at=MONDAY, window=WEEK)
        with pytest.raises(TrendError, match="consecutive"):
            Trend(TrendDirection.STEADY, recent, previous)

    def test_windows_must_have_the_same_length(self) -> None:
        recent = compute_velocity((), at=MONDAY + WEEK, window=WEEK)
        previous = compute_velocity((), at=MONDAY, window=DAY)
        with pytest.raises(TrendError, match="same length"):
            Trend(TrendDirection.STEADY, recent, previous)

    def test_direction_must_match_the_rates(self) -> None:
        recent, previous = self._velocities()
        with pytest.raises(TrendError, match="direction must match"):
            Trend(TrendDirection.DECELERATING, recent, previous)
        with pytest.raises(TrendError, match="direction must match"):
            Trend(TrendDirection.STEADY, recent, previous)

    def test_rejects_bad_fields(self) -> None:
        recent, previous = self._velocities()
        with pytest.raises(TrendError, match="direction must be"):
            Trend("accelerating", recent, previous)
        with pytest.raises(TrendError, match="recent must be"):
            Trend(TrendDirection.STEADY, "recent", previous)


class TestProjectCompletion:
    def test_projects_at_the_observed_pace(self, plan) -> None:
        task = _task(plan, 10)
        # 4h done in the week before `at` → 4/7 h per day; 6h left.
        executions = (_sitting(task, MONDAY + 6 * DAY, 9, 13),)
        at = MONDAY + 7 * DAY
        snapshot = take_progress_snapshot(plan, (task,), executions, at=at)
        velocity = compute_velocity(executions, at=at, window=WEEK)
        eta = project_completion(snapshot, velocity)
        assert snapshot.remaining == 6 * HOUR
        assert eta == at + 10.5 * DAY  # 6h at 4/7 h/day

    def test_finished_plan_has_nothing_to_project(self, plan) -> None:
        task = _task(plan, 2)
        executions = (_sitting(task, MONDAY, 9, 11),)
        at = MONDAY + DAY
        snapshot = take_progress_snapshot(plan, (task,), executions, at=at)
        velocity = compute_velocity(executions, at=at, window=WEEK)
        assert project_completion(snapshot, velocity) is None

    def test_zero_pace_never_finishes(self, plan) -> None:
        task = _task(plan, 2)
        snapshot = take_progress_snapshot(plan, (task,), (), at=MONDAY)
        velocity = compute_velocity((), at=MONDAY, window=WEEK)
        assert project_completion(snapshot, velocity) is None

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan, 2)
        snapshot = take_progress_snapshot(plan, (task,), (), at=MONDAY)
        velocity = compute_velocity((), at=MONDAY, window=WEEK)
        with pytest.raises(TrendError, match="snapshot must be"):
            project_completion("snapshot", velocity)
        with pytest.raises(TrendError, match="velocity must be"):
            project_completion(snapshot, "velocity")


class TestWiring:
    def test_trend_and_projection_read_the_same_history(self, plan) -> None:
        """Two weeks of sittings feed both the direction and the ETA —
        the trend statement and its consequence from one record set."""
        task = _task(plan, 20)
        executions = (
            _sitting(task, MONDAY, 9, 13),              # week 1: 4h
            _sitting(task, MONDAY + 8 * DAY, 9, 17),    # week 2: 8h
        )
        at = MONDAY + 14 * DAY
        snapshot = take_progress_snapshot(plan, (task,), executions, at=at)
        windows = _windows(executions, at=at, window=WEEK, count=2)
        trend = analyze_trend(windows)
        eta = project_completion(snapshot, trend.recent)

        assert trend.direction is TrendDirection.ACCELERATING
        assert snapshot.remaining == 8 * HOUR
        assert eta == at + 7 * DAY  # 8h left at 8/7 h/day
