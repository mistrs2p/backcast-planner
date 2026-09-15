"""Tests for velocity (TASK-072).

The observed work rate over a calendar window — clipped sittings,
dimensionless rate, and the per-day timedelta that projections
consume. docs/07 lists the signals; this is the base rate beneath
trend and sustainability.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.execution import create_execution
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.task import create_task
from backcasting.domain.velocity import Velocity, VelocityError, compute_velocity

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
WEEK = timedelta(days=7)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan):
    return create_task(plan, "Task", created_at=CREATED)


def _sitting(task, day, start_hour, end_hour):
    return create_execution(
        task, day.replace(hour=start_hour), day.replace(hour=end_hour),
        created_at=CREATED,
    )


class TestComputeVelocity:
    def test_work_inside_the_window_counts(self, plan) -> None:
        task = _task(plan)
        friday = MONDAY + 4 * DAY
        executions = (
            _sitting(task, MONDAY - DAY, 9, 12),  # before the window: outside
            _sitting(task, friday, 9, 12),        # inside the window
            _sitting(task, friday, 14, 16),       # inside the window
        )
        at = MONDAY + 7 * DAY
        velocity = compute_velocity(executions, at=at, window=WEEK)
        assert velocity.window_start == MONDAY
        assert velocity.window_end == at
        assert velocity.worked == 5 * HOUR

    def test_rate_is_the_window_fraction(self, plan) -> None:
        task = _task(plan)
        friday = MONDAY + 4 * DAY
        executions = (_sitting(task, friday, 9, 17),)
        velocity = compute_velocity(
            executions, at=MONDAY + 7 * DAY, window=WEEK
        )
        assert velocity.worked == 8 * HOUR
        assert velocity.rate == pytest.approx(8 / (7 * 24))

    def test_per_day_restates_the_rate(self, plan) -> None:
        task = _task(plan)
        friday = MONDAY + 4 * DAY
        executions = (_sitting(task, friday, 9, 17),)
        velocity = compute_velocity(
            executions, at=MONDAY + 7 * DAY, window=WEEK
        )
        assert velocity.per_day.total_seconds() == pytest.approx(
            (8 * HOUR / 7).total_seconds()
        )

    def test_sitting_straddling_the_window_start_is_clipped(self, plan) -> None:
        task = _task(plan)
        at = MONDAY + 7 * DAY
        # Runs 1h before the window opens, 2h into it.
        straddler = create_execution(
            task, MONDAY - HOUR, MONDAY + 2 * HOUR, created_at=CREATED
        )
        velocity = compute_velocity((straddler,), at=at, window=WEEK)
        assert velocity.worked == 2 * HOUR

    def test_sitting_straddling_the_moment_is_clipped(self, plan) -> None:
        task = _task(plan)
        at = MONDAY + 7 * DAY
        # Runs 1h before `at`, 2h after it.
        straddler = create_execution(
            task, at - HOUR, at + 2 * HOUR, created_at=CREATED
        )
        velocity = compute_velocity((straddler,), at=at, window=WEEK)
        assert velocity.worked == HOUR

    def test_fully_outside_sittings_contribute_nothing(self, plan) -> None:
        task = _task(plan)
        at = MONDAY + 7 * DAY
        executions = (
            _sitting(task, MONDAY - 3 * DAY, 9, 17),   # before the window
            _sitting(task, MONDAY + 8 * DAY, 9, 17),   # after the moment
        )
        velocity = compute_velocity(executions, at=at, window=WEEK)
        assert velocity.worked == timedelta(0)
        assert velocity.rate == 0.0

    def test_empty_reads_zero(self) -> None:
        velocity = compute_velocity((), at=MONDAY, window=WEEK)
        assert velocity.worked == timedelta(0)
        assert velocity.rate == 0.0
        assert velocity.per_day == timedelta(0)

    def test_window_is_calendar_time_not_workable_time(self, plan) -> None:
        """No availability is consulted: a 1-week window is 168h of
        denominator, whatever the calendar says is workable."""
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 9, 17),)
        velocity = compute_velocity(executions, at=MONDAY + WEEK, window=WEEK)
        assert velocity.rate == pytest.approx(8 / 168)

    def test_one_day_window(self, plan) -> None:
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 9, 12), _sitting(task, MONDAY, 13, 17))
        velocity = compute_velocity(executions, at=MONDAY + DAY, window=DAY)
        assert velocity.worked == 7 * HOUR
        assert velocity.per_day == 7 * HOUR

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan)
        with pytest.raises(VelocityError, match="executions must be a tuple"):
            compute_velocity([], at=MONDAY, window=WEEK)
        with pytest.raises(VelocityError, match="Execution instances"):
            compute_velocity(("x",), at=MONDAY, window=WEEK)
        with pytest.raises(VelocityError, match="at must be"):
            compute_velocity((), at=datetime(2026, 6, 8), window=WEEK)
        with pytest.raises(VelocityError, match="window must be"):
            compute_velocity((), at=MONDAY, window=timedelta(0))
        with pytest.raises(VelocityError, match="window must be"):
            compute_velocity((), at=MONDAY, window=-HOUR)
        with pytest.raises(VelocityError, match="window must be"):
            compute_velocity((), at=MONDAY, window="week")


class TestVelocityRecord:
    def test_is_immutable(self) -> None:
        velocity = compute_velocity((), at=MONDAY, window=WEEK)
        with pytest.raises(AttributeError):
            velocity.rate = 0.5  # type: ignore[misc]

    def test_direct_construction_validates(self) -> None:
        kwargs = dict(
            window_start=MONDAY,
            window_end=MONDAY + WEEK,
            worked=10 * HOUR,
            rate=10 / 168,
        )
        assert isinstance(Velocity(**kwargs), Velocity)
        with pytest.raises(VelocityError, match="window_end must be after"):
            Velocity(**dict(kwargs, window_end=MONDAY))
        with pytest.raises(VelocityError, match="worked must be"):
            Velocity(**dict(kwargs, worked=-HOUR))
        with pytest.raises(VelocityError, match="rate must be within"):
            Velocity(**dict(kwargs, rate=1.5))
        with pytest.raises(VelocityError, match="window_start must be"):
            Velocity(**dict(kwargs, window_start=datetime(2026, 6, 1)))


class TestWiring:
    def test_velocity_projects_the_remaining_workload(self, plan) -> None:
        """remaining ÷ per-day pace = calendar time to finish at the
        observed velocity — the raw material of trend (docs/07)."""
        from backcasting.domain.progress import take_progress_snapshot
        from backcasting.domain.task import revise_task
        from backcasting.domain.task_estimation import estimate_workload

        task = _task(plan)
        task = revise_task(task, duration=10 * HOUR, updated_at=CREATED)
        # Two full workdays recorded inside the week before `at`.
        executions = (
            _sitting(task, MONDAY + 5 * DAY, 9, 17),
            _sitting(task, MONDAY + 6 * DAY, 9, 17),
        )
        at = MONDAY + 7 * DAY
        snapshot = take_progress_snapshot(plan, (task,), executions, at=at)
        velocity = compute_velocity(executions, at=at, window=WEEK)

        assert snapshot.actual == 16 * HOUR
        assert snapshot.remaining == timedelta(0)  # done, with overwork
        # A task with room left: 10h planned, only 4h done this week.
        slower = revise_task(task, duration=10 * HOUR, updated_at=CREATED)
        partial = (_sitting(task, MONDAY + 5 * DAY, 9, 13),)
        snap = take_progress_snapshot(plan, (slower,), partial, at=at)
        vel = compute_velocity(partial, at=at, window=WEEK)
        days_left = snap.remaining / vel.per_day
        # 6h left at 4h/7days ≈ 0.571 h/day → 10.5 days.
        assert days_left == pytest.approx(10.5)
        assert estimate_workload((slower,)) == 10 * HOUR
