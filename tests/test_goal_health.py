"""Tests for goal health (TASK-075).

The roll-up of the docs/07 signals: on-time rate (the last signal
on the list) and the categorical health reading whose every trigger
leaves a machine-readable reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.execution import create_execution
from backcasting.domain.goal import create_goal
from backcasting.domain.goal_health import (
    GoalHealth,
    GoalHealthError,
    GoalHealthStatus,
    assess_goal_health,
    on_time_rate,
)
from backcasting.domain.plan import create_plan
from backcasting.domain.progress import take_progress_snapshot
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.trend import Trend, TrendDirection
from backcasting.domain.variance import Variance, VarianceKind

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, hours, deadline=None):
    task = create_task(plan, "Task", deadline=deadline, created_at=CREATED)
    return revise_task(task, duration=timedelta(hours=hours), updated_at=CREATED)


def _sitting(task, day, start_hour, end_hour):
    day = day.replace(hour=start_hour)
    return create_execution(task, day, day.replace(hour=end_hour), created_at=CREATED)


def _snapshot(plan, tasks, executions, at):
    return take_progress_snapshot(plan, tasks, executions, at=at)


class TestOnTimeRate:
    def test_all_on_time(self, plan) -> None:
        deadline = MONDAY.replace(hour=17)
        a = _task(plan, 2, deadline=deadline)
        b = _task(plan, 1, deadline=deadline)
        executions = (_sitting(a, MONDAY, 9, 11), _sitting(b, MONDAY, 13, 14))
        rate = on_time_rate((a, b), executions, at=MONDAY + timedelta(days=1))
        assert rate == 1.0

    def test_one_late_one_on_time(self, plan) -> None:
        deadline = MONDAY.replace(hour=12)
        punctual = _task(plan, 2, deadline=deadline)
        late = _task(plan, 2, deadline=deadline)
        executions = (
            _sitting(punctual, MONDAY, 9, 11),
            _sitting(late, MONDAY, 13, 15),  # finished after the deadline
        )
        rate = on_time_rate(
            (punctual, late), executions, at=MONDAY + timedelta(days=1)
        )
        assert rate == 0.5

    def test_late_sitting_after_an_on_time_finish_does_not_count(self, plan) -> None:
        """The completion moment is when the workload first reaches
        the estimate; later sittings are overwork, not lateness."""
        deadline = MONDAY.replace(hour=12)
        task = _task(plan, 2, deadline=deadline)
        executions = (
            _sitting(task, MONDAY, 9, 11),    # crosses the line at 11:00
            _sitting(task, MONDAY, 14, 15),   # overwork after the deadline
        )
        rate = on_time_rate((task,), executions, at=MONDAY + timedelta(days=1))
        assert rate == 1.0

    def test_completion_exactly_at_the_deadline_is_on_time(self, plan) -> None:
        deadline = MONDAY.replace(hour=11)
        task = _task(plan, 2, deadline=deadline)
        executions = (_sitting(task, MONDAY, 9, 11),)
        rate = on_time_rate((task,), executions, at=MONDAY + timedelta(days=1))
        assert rate == 1.0

    def test_unfinished_tasks_are_not_counted(self, plan) -> None:
        deadline = MONDAY.replace(hour=17)
        finished = _task(plan, 2, deadline=deadline)
        started = _task(plan, 4, deadline=deadline)
        executions = (
            _sitting(finished, MONDAY, 9, 11),
            _sitting(started, MONDAY, 13, 15),  # only half done
        )
        rate = on_time_rate(
            (finished, started), executions, at=MONDAY + timedelta(days=1)
        )
        assert rate == 1.0

    def test_deadlineless_tasks_are_not_counted(self, plan) -> None:
        free = _task(plan, 2)
        executions = (_sitting(free, MONDAY, 9, 11),)
        assert on_time_rate((free,), executions, at=MONDAY) is None

    def test_no_finished_tasks_is_none(self, plan) -> None:
        deadline = MONDAY.replace(hour=17)
        task = _task(plan, 2, deadline=deadline)
        assert on_time_rate((task,), (), at=MONDAY) is None

    def test_sittings_after_the_moment_do_not_count(self, plan) -> None:
        deadline = MONDAY.replace(hour=17)
        task = _task(plan, 2, deadline=deadline)
        executions = (_sitting(task, MONDAY, 15, 17),)
        noon = MONDAY.replace(hour=12)
        assert on_time_rate((task,), executions, at=noon) is None

    def test_unestimated_deadline_task_errors(self, plan) -> None:
        deadline = MONDAY.replace(hour=17)
        unestimated = create_task(plan, "Draft", deadline=deadline, created_at=CREATED)
        with pytest.raises(GoalHealthError, match="has no estimate"):
            on_time_rate((unestimated,), (), at=MONDAY)

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan, 2)
        with pytest.raises(GoalHealthError, match="tasks must be a tuple"):
            on_time_rate([], (), at=MONDAY)
        with pytest.raises(GoalHealthError, match="Task instances"):
            on_time_rate(("x",), (), at=MONDAY)
        with pytest.raises(GoalHealthError, match="executions must be a tuple"):
            on_time_rate((task,), [], at=MONDAY)
        with pytest.raises(GoalHealthError, match="Execution instances"):
            on_time_rate((task,), ("x",), at=MONDAY)
        with pytest.raises(GoalHealthError, match="at must be"):
            on_time_rate((task,), (), at=datetime(2026, 6, 1))


class TestAssessGoalHealth:
    def test_complete_plan_is_on_track(self, plan) -> None:
        task = _task(plan, 2)
        snapshot = _snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 11),), at=MONDAY + HOUR * 12
        )
        health = assess_goal_health(snapshot)
        assert health.status is GoalHealthStatus.ON_TRACK
        assert health.reasons == ("plan-complete",)

    def test_no_adverse_signals_is_on_track(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = _snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 11),), at=MONDAY + HOUR * 12
        )
        health = assess_goal_health(snapshot)
        assert health.status is GoalHealthStatus.ON_TRACK
        assert health.reasons == ()

    def test_projected_miss_is_off_track(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = _snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 11),), at=MONDAY + HOUR * 12
        )
        deadline = MONDAY + timedelta(days=2)
        late_eta = MONDAY + timedelta(days=5)
        health = assess_goal_health(
            snapshot, deadline=deadline, projected_completion=late_eta
        )
        assert health.status is GoalHealthStatus.OFF_TRACK
        assert "projected-deadline-miss" in health.reasons

    def test_projection_meeting_the_deadline_is_not_off_track(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = _snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 11),), at=MONDAY + HOUR * 12
        )
        health = assess_goal_health(
            snapshot,
            deadline=MONDAY + timedelta(days=7),
            projected_completion=MONDAY + timedelta(days=5),
        )
        assert health.status is GoalHealthStatus.ON_TRACK

    def test_projection_without_deadline_is_not_judged(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = _snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 11),), at=MONDAY + HOUR * 12
        )
        health = assess_goal_health(
            snapshot, projected_completion=MONDAY + timedelta(days=99)
        )
        assert health.status is GoalHealthStatus.ON_TRACK

    def test_unfavorable_variance_is_at_risk(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = _snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 10),), at=MONDAY + HOUR * 12
        )
        from backcasting.domain.variance import progress_variance

        health = assess_goal_health(snapshot, variances=(progress_variance(snapshot),))
        assert health.status is GoalHealthStatus.AT_RISK
        assert health.reasons == ("unfavorable-progress-variance",)

    def test_each_unfavorable_variance_leaves_its_reason(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = _snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 10),), at=MONDAY + HOUR * 12
        )
        from backcasting.domain.variance import progress_variance, schedule_variance

        variances = (
            progress_variance(snapshot),
            schedule_variance((), ()),  # vacuously favorable
        )
        health = assess_goal_health(snapshot, variances=variances)
        assert health.reasons == ("unfavorable-progress-variance",)

    def test_decelerating_trend_is_at_risk(self, plan) -> None:
        from dataclasses import replace

        from backcasting.domain.velocity import compute_velocity

        task = _task(plan, 40)
        snapshot = _snapshot(plan, (task,), (), at=MONDAY)
        recent = compute_velocity((), at=MONDAY + 2 * WEEK, window=WEEK)
        previous = compute_velocity((), at=MONDAY + WEEK, window=WEEK)
        trend = Trend(
            TrendDirection.DECELERATING,
            replace(recent, worked=2 * HOUR, rate=2 / (7 * 24)),
            replace(previous, worked=8 * HOUR, rate=8 / (7 * 24)),
        )
        health = assess_goal_health(snapshot, trend=trend)
        assert health.status is GoalHealthStatus.AT_RISK
        assert "decelerating-trend" in health.reasons

    def test_steady_trend_is_not_adverse(self, plan) -> None:
        from backcasting.domain.velocity import compute_velocity

        task = _task(plan, 40)
        snapshot = _snapshot(plan, (task,), (), at=MONDAY)
        steady = Trend(
            TrendDirection.STEADY,
            compute_velocity((), at=MONDAY + 2 * WEEK, window=WEEK),
            compute_velocity((), at=MONDAY + WEEK, window=WEEK),
        )
        health = assess_goal_health(snapshot, trend=steady)
        assert health.status is GoalHealthStatus.ON_TRACK

    def test_late_completions_are_at_risk(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = _snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 10),), at=MONDAY + HOUR * 12
        )
        health = assess_goal_health(snapshot, on_time=0.5)
        assert health.status is GoalHealthStatus.AT_RISK
        assert "late-completions" in health.reasons

    def test_off_track_outranks_at_risk(self, plan) -> None:
        task = _task(plan, 4)
        snapshot = _snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 10),), at=MONDAY + HOUR * 12
        )
        from backcasting.domain.variance import progress_variance

        health = assess_goal_health(
            snapshot,
            variances=(progress_variance(snapshot),),
            deadline=MONDAY + timedelta(days=2),
            projected_completion=MONDAY + timedelta(days=5),
            on_time=0.5,
        )
        assert health.status is GoalHealthStatus.OFF_TRACK
        assert health.reasons == (
            "projected-deadline-miss",
            "unfavorable-progress-variance",
            "late-completions",
        )

    def test_complete_plan_outranks_everything(self, plan) -> None:
        """A finished plan is healthy even if the trend is poor and
        the projections look late — there is nothing left to project."""
        task = _task(plan, 2)
        snapshot = _snapshot(
            plan, (task,), (_sitting(task, MONDAY, 9, 11),), at=MONDAY + HOUR * 12
        )
        health = assess_goal_health(
            snapshot,
            deadline=MONDAY + timedelta(days=2),
            projected_completion=MONDAY + timedelta(days=5),
            on_time=0.0,
        )
        assert health.status is GoalHealthStatus.ON_TRACK
        assert health.reasons == ("plan-complete",)

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan, 2)
        snapshot = _snapshot(plan, (task,), (), at=MONDAY)
        with pytest.raises(GoalHealthError, match="snapshot must be"):
            assess_goal_health("snapshot")
        with pytest.raises(GoalHealthError, match="variances must be a tuple"):
            assess_goal_health(snapshot, variances=[])
        with pytest.raises(GoalHealthError, match="Variance instances"):
            assess_goal_health(snapshot, variances=("x",))
        with pytest.raises(GoalHealthError, match="trend must be"):
            assess_goal_health(snapshot, trend="decelerating")
        with pytest.raises(GoalHealthError, match="deadline must be"):
            assess_goal_health(snapshot, deadline=datetime(2026, 6, 1))
        with pytest.raises(GoalHealthError, match="projected_completion must be"):
            assess_goal_health(snapshot, projected_completion=datetime(2026, 6, 1))
        with pytest.raises(GoalHealthError, match="on_time must be a number"):
            assess_goal_health(snapshot, on_time="all")
        with pytest.raises(GoalHealthError, match="on_time must be within"):
            assess_goal_health(snapshot, on_time=1.5)


class TestGoalHealthRecord:
    def test_is_immutable(self, plan) -> None:
        health = GoalHealth(GoalHealthStatus.ON_TRACK, ())
        with pytest.raises(AttributeError):
            health.status = GoalHealthStatus.AT_RISK  # type: ignore[misc]

    def test_non_on_track_readings_need_reasons(self) -> None:
        with pytest.raises(GoalHealthError, match="must carry reasons"):
            GoalHealth(GoalHealthStatus.AT_RISK, ())
        with pytest.raises(GoalHealthError, match="must carry reasons"):
            GoalHealth(GoalHealthStatus.OFF_TRACK, ())

    def test_rejects_bad_fields(self) -> None:
        with pytest.raises(GoalHealthError, match="status must be"):
            GoalHealth("on_track", ())
        with pytest.raises(GoalHealthError, match="reasons must be a tuple"):
            GoalHealth(GoalHealthStatus.AT_RISK, ["reason"])
        with pytest.raises(GoalHealthError, match="non-empty strings"):
            GoalHealth(GoalHealthStatus.AT_RISK, ("",))


class TestWiring:
    def test_full_signal_chain_into_health(self, plan) -> None:
        """Snapshot, variance, trend and projection feed one reading;
        the on-time rate comes from the same sitting history."""
        from backcasting.domain.trend import analyze_trend, project_completion
        from backcasting.domain.variance import progress_variance
        from backcasting.domain.velocity import compute_velocity

        task = _task(plan, 10, deadline=MONDAY + timedelta(days=14))
        executions = (
            _sitting(task, MONDAY, 9, 13),              # morning: 4h
            _sitting(task, MONDAY + 8 * HOUR, 14, 18),  # afternoon: 4h more
        )
        at = MONDAY + timedelta(days=7)
        week = timedelta(days=7)
        windows = (
            compute_velocity(executions, at=at - week, window=week),
            compute_velocity(executions, at=at, window=week),
        )
        trend = analyze_trend(windows)
        snapshot = _snapshot(plan, (task,), executions, at=at)
        eta = project_completion(snapshot, trend.recent)
        rate = on_time_rate((task,), executions, at=at)

        # One worked Monday within the recent week: 8h of a 10h task
        # at a 8h/week pace.
        assert snapshot.remaining == 2 * HOUR
        assert trend.direction is TrendDirection.ACCELERATING
        assert eta == at + 42 * HOUR  # 2h left at 8h per 7 days = 1.75 days
        assert rate is None  # the task has not finished
        health = assess_goal_health(
            snapshot,
            variances=(progress_variance(snapshot),),
            trend=trend,
            deadline=task.deadline,
            projected_completion=eta,
            on_time=rate,
        )
        assert health.status is GoalHealthStatus.AT_RISK
        assert health.reasons == ("unfavorable-progress-variance",)
