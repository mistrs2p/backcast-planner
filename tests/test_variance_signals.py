"""Tests for the variance signals (TASK-073).

docs/07's four time-denominated variances — progress, time, capacity,
schedule — one record shape, one sign convention (delta =
actual - planned), each with its inherent direction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from backcasting.domain.availability import create_availability_window
from backcasting.domain.calendar import create_calendar
from backcasting.domain.calendar_event import create_event
from backcasting.domain.execution import create_execution
from backcasting.domain.goal import create_goal
from backcasting.domain.observed_capacity import measure_observed_capacity
from backcasting.domain.plan import create_plan
from backcasting.domain.progress import take_progress_snapshot
from backcasting.domain.schedule import create_schedule
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.variance import (
    Variance,
    VarianceError,
    VarianceKind,
    capacity_variance,
    progress_variance,
    schedule_variance,
    time_variance,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)


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


class TestVarianceRecord:
    def _kwargs(self) -> dict:
        return dict(
            kind=VarianceKind.PROGRESS,
            planned=4 * HOUR,
            actual=3 * HOUR,
            delta=-HOUR,
            favorable=False,
        )

    def test_valid_construction(self) -> None:
        variance = Variance(**self._kwargs())
        assert variance.kind is VarianceKind.PROGRESS
        assert variance.delta == variance.actual - variance.planned

    def test_kinds_match_the_spec(self) -> None:
        assert {k.value for k in VarianceKind} == {
            "progress", "time", "capacity", "schedule",
        }

    def test_delta_must_be_consistent(self) -> None:
        with pytest.raises(VarianceError, match="delta must equal"):
            Variance(**dict(self._kwargs(), delta=HOUR))

    def test_rejects_bad_fields(self) -> None:
        with pytest.raises(VarianceError, match="kind must be"):
            Variance(**dict(self._kwargs(), kind="progress"))
        with pytest.raises(VarianceError, match="planned must be"):
            Variance(**dict(self._kwargs(), planned=-HOUR))
        with pytest.raises(VarianceError, match="actual must be"):
            Variance(**dict(self._kwargs(), actual="3 hours"))
        with pytest.raises(VarianceError, match="favorable must be"):
            Variance(**dict(self._kwargs(), favorable="yes"))


class TestProgressVariance:
    def test_under_plan_is_unfavorable(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = take_progress_snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 11),), at=MONDAY + timedelta(days=1)
        )
        variance = progress_variance(snapshot)
        assert variance.kind is VarianceKind.PROGRESS
        assert variance.planned == 4 * HOUR
        assert variance.actual == 2 * HOUR
        assert variance.delta == -2 * HOUR
        assert variance.favorable is False

    def test_meeting_or_outrunning_the_plan_is_favorable(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = take_progress_snapshot(
            plan,
            (task,),
            (_sitting(task, MONDAY, 9, 13),),
            at=MONDAY + timedelta(days=1),
        )
        assert progress_variance(snapshot).favorable is True

    def test_rejects_non_snapshot(self) -> None:
        with pytest.raises(VarianceError, match="snapshot must be"):
            progress_variance("snapshot")


class TestTimeVariance:
    def test_overrun_is_unfavorable(self, plan) -> None:
        task = _task(plan, 2)
        executions = (_sitting(task, MONDAY, 9, 10), _sitting(task, MONDAY, 11, 12))
        variance = time_variance(task, executions)
        assert variance.kind is VarianceKind.TIME
        assert variance.planned == 2 * HOUR
        assert variance.actual == 2 * HOUR
        assert variance.delta == timedelta(0)
        assert variance.favorable is True

    def test_taking_longer_than_estimated_is_unfavorable(self, plan) -> None:
        task = _task(plan, 2)
        executions = (_sitting(task, MONDAY, 9, 13),)  # 4h for a 2h estimate
        variance = time_variance(task, executions)
        assert variance.delta == 2 * HOUR
        assert variance.favorable is False

    def test_under_run_is_favorable(self, plan) -> None:
        task = _task(plan, 4)
        executions = (_sitting(task, MONDAY, 9, 11),)
        variance = time_variance(task, executions)
        assert variance.delta == -2 * HOUR
        assert variance.favorable is True

    def test_executions_of_other_tasks_are_ignored(self, plan) -> None:
        mine, other = _task(plan, 2), _task(plan, 2)
        variance = time_variance(mine, (_sitting(other, MONDAY, 9, 17),))
        assert variance.actual == timedelta(0)

    def test_unestimated_task_has_no_planned_side(self, plan) -> None:
        unestimated = create_task(plan, "Draft", created_at=CREATED)
        with pytest.raises(VarianceError, match="has no estimate"):
            time_variance(unestimated, ())

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan, 2)
        with pytest.raises(TypeError, match="task must be a Task"):
            time_variance("task", ())
        with pytest.raises(VarianceError, match="executions must be a tuple"):
            time_variance(task, [])
        with pytest.raises(VarianceError, match="Execution instances"):
            time_variance(task, ("x",))


class TestCapacityVariance:
    @pytest.fixture
    def calendar(self):
        return create_calendar(uuid.uuid4(), created_at=CREATED)

    @pytest.fixture
    def weekdays(self):
        return frozenset({0, 1, 2, 3, 4, 5, 6})  # every day

    def test_planned_recomputed_over_the_observed_period(self, calendar, weekdays) -> None:
        window = create_availability_window(
            calendar, weekdays, time(9), time(17), created_at=CREATED
        )
        observed = measure_observed_capacity(
            calendar,
            (window,),
            (),
            range_start=MONDAY,
            range_end=MONDAY + timedelta(days=1),
            measured_at=MONDAY + timedelta(days=1),
        )
        variance = capacity_variance((window,), (), observed)
        assert variance.kind is VarianceKind.CAPACITY
        assert variance.planned == 8 * HOUR
        assert variance.actual == 8 * HOUR
        assert variance.favorable is True

    def test_events_shrink_both_sides_equally(self, calendar, weekdays) -> None:
        """An event that occupied the calendar is not a capacity
        shortfall: it was never workable, planned or observed."""
        window = create_availability_window(
            calendar, weekdays, time(9), time(17), created_at=CREATED
        )
        meeting = create_event(
            calendar, "All-hands", MONDAY.replace(hour=9), MONDAY.replace(hour=11),
            created_at=CREATED,
        )
        observed = measure_observed_capacity(
            calendar,
            (window,),
            (meeting,),
            range_start=MONDAY,
            range_end=MONDAY + timedelta(days=1),
            measured_at=MONDAY + timedelta(days=1),
        )
        variance = capacity_variance((window,), (meeting,), observed)
        assert variance.planned == 6 * HOUR
        assert variance.actual == 6 * HOUR
        assert variance.favorable is True

    def test_shortfall_is_unfavorable(self, calendar, weekdays) -> None:
        """A window removed after planning: the planned side still
        counts it, the observed record does not."""
        planned_with = create_availability_window(
            calendar, weekdays, time(9), time(17), created_at=CREATED
        )
        observed = measure_observed_capacity(
            calendar,
            (),
            (),
            range_start=MONDAY,
            range_end=MONDAY + timedelta(days=1),
            measured_at=MONDAY + timedelta(days=1),
        )
        variance = capacity_variance((planned_with,), (), observed)
        assert variance.planned == 8 * HOUR
        assert variance.actual == timedelta(0)
        assert variance.delta == -8 * HOUR
        assert variance.favorable is False

    def test_rejects_non_observed(self) -> None:
        with pytest.raises(VarianceError, match="observed must be"):
            capacity_variance((), (), "observed")

    def test_rejects_bad_windows(self, calendar) -> None:
        observed = measure_observed_capacity(
            calendar, (), (), range_start=MONDAY,
            range_end=MONDAY + timedelta(days=1),
            measured_at=MONDAY + timedelta(days=1),
        )
        with pytest.raises(VarianceError):
            capacity_variance(("x",), (), observed)


class TestScheduleVariance:
    def test_fully_worked_placement_is_favorable(self, plan) -> None:
        task = _task(plan, 2)
        schedule = create_schedule(
            task, MONDAY.replace(hour=9), MONDAY.replace(hour=11), created_at=CREATED
        )
        execution = _sitting(task, MONDAY, 9, 11)
        variance = schedule_variance((schedule,), (execution,))
        assert variance.kind is VarianceKind.SCHEDULE
        assert variance.planned == 2 * HOUR
        assert variance.actual == 2 * HOUR
        assert variance.favorable is True

    def test_partially_worked_placement(self, plan) -> None:
        task = _task(plan, 4)
        schedule = create_schedule(
            task, MONDAY.replace(hour=9), MONDAY.replace(hour=13), created_at=CREATED
        )
        execution = _sitting(task, MONDAY, 10, 12)  # late start, early stop
        variance = schedule_variance((schedule,), (execution,))
        assert variance.actual == 2 * HOUR
        assert variance.delta == -2 * HOUR
        assert variance.favorable is False

    def test_work_outside_the_placement_does_not_count(self, plan) -> None:
        task = _task(plan, 2)
        schedule = create_schedule(
            task, MONDAY.replace(hour=9), MONDAY.replace(hour=11), created_at=CREATED
        )
        execution = _sitting(task, MONDAY, 15, 19)  # same total, wrong time
        variance = schedule_variance((schedule,), (execution,))
        assert variance.actual == timedelta(0)
        assert variance.favorable is False

    def test_execution_straddling_the_placement_is_clipped(self, plan) -> None:
        task = _task(plan, 4)
        schedule = create_schedule(
            task, MONDAY.replace(hour=10), MONDAY.replace(hour=12), created_at=CREATED
        )
        execution = _sitting(task, MONDAY, 9, 13)  # overruns both edges
        variance = schedule_variance((schedule,), (execution,))
        assert variance.planned == 2 * HOUR
        assert variance.actual == 2 * HOUR

    def test_executions_of_other_tasks_are_ignored(self, plan) -> None:
        mine, other = _task(plan, 2), _task(plan, 2)
        schedule = create_schedule(
            mine, MONDAY.replace(hour=9), MONDAY.replace(hour=11), created_at=CREATED
        )
        variance = schedule_variance((schedule,), (_sitting(other, MONDAY, 9, 11),))
        assert variance.actual == timedelta(0)

    def test_split_placements_sum(self, plan) -> None:
        task = _task(plan, 4)
        schedules = (
            create_schedule(
                task, MONDAY.replace(hour=9), MONDAY.replace(hour=11), created_at=CREATED
            ),
            create_schedule(
                task,
                MONDAY.replace(hour=14),
                MONDAY.replace(hour=16),
                created_at=CREATED,
            ),
        )
        executions = (_sitting(task, MONDAY, 9, 11),)
        variance = schedule_variance(schedules, executions)
        assert variance.planned == 4 * HOUR
        assert variance.actual == 2 * HOUR

    def test_no_placements_is_vacuously_favorable(self) -> None:
        variance = schedule_variance((), ())
        assert variance.planned == timedelta(0)
        assert variance.actual == timedelta(0)
        assert variance.favorable is True

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan, 2)
        with pytest.raises(VarianceError, match="schedules must be a tuple"):
            schedule_variance([], ())
        with pytest.raises(VarianceError, match="Schedule instances"):
            schedule_variance(("x",), ())
        with pytest.raises(VarianceError, match="executions must be a tuple"):
            schedule_variance((), [])
        with pytest.raises(VarianceError, match="Execution instances"):
            schedule_variance((), ("x",))


class TestWiring:
    def test_one_week_four_signals(self, plan) -> None:
        """The full feedback story: a 2h task placed Monday morning,
        worked late instead, on a day whose capacity shrank."""
        from backcasting.domain.availability import create_availability_window
        from backcasting.domain.calendar import create_calendar
        from backcasting.domain.observed_capacity import measure_observed_capacity

        task = _task(plan, 2)
        schedule = create_schedule(
            task, MONDAY.replace(hour=9), MONDAY.replace(hour=11), created_at=CREATED
        )
        execution = _sitting(task, MONDAY, 15, 18)  # moved, and overran

        snapshot = take_progress_snapshot(
            plan, (task,), (execution,), at=MONDAY + timedelta(days=1)
        )
        signals = {
            "progress": progress_variance(snapshot),
            "time": time_variance(task, (execution,)),
            "schedule": schedule_variance((schedule,), (execution,)),
        }

        assert signals["progress"].planned == 2 * HOUR
        assert signals["progress"].actual == 3 * HOUR
        assert signals["progress"].favorable is True  # more done than planned
        assert signals["time"].actual == 3 * HOUR
        assert signals["time"].favorable is False  # but it took longer
        assert signals["schedule"].actual == timedelta(0)
        assert signals["schedule"].favorable is False  # and not when placed

        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        window = create_availability_window(
            calendar, frozenset({0, 1, 2, 3, 4, 5, 6}), time(9), time(17),
            created_at=CREATED,
        )
        # Planned around a clear day; a lunch event then occupied an
        # hour of what was supposed to be workable.
        lunch = create_event(
            calendar, "Lunch", MONDAY.replace(hour=12), MONDAY.replace(hour=13),
            created_at=CREATED,
        )
        observed = measure_observed_capacity(
            calendar,
            (window,),
            (lunch,),
            range_start=MONDAY,
            range_end=MONDAY + timedelta(days=1),
            measured_at=MONDAY + timedelta(days=1),
        )
        capacity = capacity_variance((window,), (), observed)
        assert capacity.planned == 8 * HOUR
        assert capacity.actual == 7 * HOUR
        assert capacity.delta == -HOUR
        assert capacity.favorable is False
