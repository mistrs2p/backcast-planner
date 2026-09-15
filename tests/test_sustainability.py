"""Tests for sustainability (TASK-076).

The observed pace against the workable time over the same window:
utilization vs a ceiling, with work beyond the declared availability
unsustainable whatever the ceiling.
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
from backcasting.domain.plan import create_plan
from backcasting.domain.sustainability import (
    Sustainability,
    SustainabilityError,
    SustainabilityStatus,
    assess_sustainability,
)
from backcasting.domain.task import create_task
from backcasting.domain.velocity import compute_velocity

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
WEEK = timedelta(days=7)
MONDAYS = frozenset({0})  # one workday per week, for readable ratios


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan):
    return create_task(plan, "Task", created_at=CREATED)


def _sitting(task, day, start_hour, end_hour):
    day = day.replace(hour=start_hour)
    return create_execution(task, day, day.replace(hour=end_hour), created_at=CREATED)


def _velocity(executions, *, at, window):
    return compute_velocity(executions, at=at, window=window)


class TestAssessSustainability:
    @pytest.fixture
    def calendar(self):
        return create_calendar(uuid.uuid4(), created_at=CREATED)

    @pytest.fixture
    def nine_to_five(self, calendar):
        # Mondays 09:00-17:00: 8h of workable time per week-long window.
        return create_availability_window(
            calendar, MONDAYS, time(9), time(17), created_at=CREATED
        )

    def test_within_capacity_is_sustainable(
        self, plan, calendar, nine_to_five
    ) -> None:
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 9, 17),)  # exactly the window
        velocity = _velocity(executions, at=MONDAY + WEEK, window=WEEK)
        reading = assess_sustainability(velocity, (nine_to_five,))
        assert reading.status is SustainabilityStatus.SUSTAINABLE
        assert reading.worked == 8 * HOUR
        assert reading.workable == 8 * HOUR  # the window covers only Monday
        assert reading.utilization == 1.0

    def test_beyond_capacity_is_unsustainable(
        self, plan, calendar, nine_to_five
    ) -> None:
        """Evening work outside the declared window: the hours come
        from somewhere the user did not declare as workable."""
        task = _task(plan)
        executions = (
            _sitting(task, MONDAY, 9, 17),
            _sitting(task, MONDAY, 19, 21),  # the burnout signal
        )
        velocity = _velocity(executions, at=MONDAY + WEEK, window=WEEK)
        reading = assess_sustainability(velocity, (nine_to_five,))
        assert reading.status is SustainabilityStatus.UNSUSTAINABLE
        assert reading.worked == 10 * HOUR
        assert reading.utilization == 10 / 8

    def test_events_shrink_the_workable_side(
        self, plan, calendar, nine_to_five
    ) -> None:
        task = _task(plan)
        meeting = create_event(
            calendar, "All-hands", MONDAY.replace(hour=9), MONDAY.replace(hour=11),
            created_at=CREATED,
        )
        executions = (_sitting(task, MONDAY, 11, 17),)  # 6h, within the remains
        velocity = _velocity(executions, at=MONDAY + WEEK, window=WEEK)
        reading = assess_sustainability(velocity, (nine_to_five,), (meeting,))
        assert reading.workable == 6 * HOUR
        assert reading.utilization == 1.0
        assert reading.status is SustainabilityStatus.SUSTAINABLE

    def test_lower_ceiling_flags_headroom_pressure(
        self, plan, calendar, nine_to_five
    ) -> None:
        """A 0.8 policy ceiling: working 100% of the declared time is
        sustainable by declaration, but not by policy."""
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 9, 17),)
        velocity = _velocity(executions, at=MONDAY + WEEK, window=WEEK)
        reading = assess_sustainability(velocity, (nine_to_five,), max_utilization=0.8)
        assert reading.status is SustainabilityStatus.UNSUSTAINABLE
        assert reading.max_utilization == 0.8

    def test_partial_utilization_is_sustainable(
        self, plan, calendar, nine_to_five
    ) -> None:
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 9, 13),)
        velocity = _velocity(executions, at=MONDAY + WEEK, window=WEEK)
        reading = assess_sustainability(velocity, (nine_to_five,))
        assert reading.utilization == 0.5
        assert reading.status is SustainabilityStatus.SUSTAINABLE

    def test_no_workable_time_and_no_work(self, plan, calendar) -> None:
        velocity = _velocity((), at=MONDAY + WEEK, window=WEEK)
        reading = assess_sustainability(velocity, ())
        assert reading.workable == timedelta(0)
        assert reading.utilization is None
        assert reading.status is SustainabilityStatus.SUSTAINABLE

    def test_work_over_zero_workable_time_is_unsustainable(
        self, plan, calendar
    ) -> None:
        """No declared availability, yet work happened: beyond
        capacity by definition."""
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 20, 22),)
        velocity = _velocity(executions, at=MONDAY + WEEK, window=WEEK)
        reading = assess_sustainability(velocity, ())
        assert reading.utilization is None
        assert reading.status is SustainabilityStatus.UNSUSTAINABLE

    def test_rejects_bad_arguments(self, plan, calendar, nine_to_five) -> None:
        velocity = _velocity((), at=MONDAY + WEEK, window=WEEK)
        with pytest.raises(SustainabilityError, match="velocity must be"):
            assess_sustainability("velocity", ())
        with pytest.raises(SustainabilityError, match="windows must be a tuple"):
            assess_sustainability(velocity, [])
        with pytest.raises(SustainabilityError, match="AvailabilityWindow instances"):
            assess_sustainability(velocity, ("x",))
        with pytest.raises(SustainabilityError, match="events must be a tuple"):
            assess_sustainability(velocity, (nine_to_five,), [])
        with pytest.raises(SustainabilityError, match="CalendarEvent instances"):
            assess_sustainability(velocity, (nine_to_five,), ("x",))
        with pytest.raises(SustainabilityError, match="max_utilization must be a number"):
            assess_sustainability(velocity, (), max_utilization="all")
        with pytest.raises(SustainabilityError, match="max_utilization must be within"):
            assess_sustainability(velocity, (), max_utilization=0.0)
        with pytest.raises(SustainabilityError, match="max_utilization must be within"):
            assess_sustainability(velocity, (), max_utilization=1.5)


class TestSustainabilityRecord:
    def _kwargs(self) -> dict:
        return dict(
            status=SustainabilityStatus.SUSTAINABLE,
            worked=6 * HOUR,
            workable=8 * HOUR,
            utilization=0.75,
            max_utilization=1.0,
        )

    def test_valid_construction(self) -> None:
        reading = Sustainability(**self._kwargs())
        assert reading.status is SustainabilityStatus.SUSTAINABLE

    def test_utilization_must_match_the_sides(self) -> None:
        with pytest.raises(SustainabilityError, match="utilization must equal"):
            Sustainability(**dict(self._kwargs(), utilization=0.5))

    def test_status_must_match_the_utilization(self) -> None:
        with pytest.raises(SustainabilityError, match="status must match"):
            Sustainability(
                **dict(self._kwargs(), status=SustainabilityStatus.UNSUSTAINABLE)
            )
        with pytest.raises(SustainabilityError, match="status must match"):
            Sustainability(
                **dict(
                    self._kwargs(),
                    status=SustainabilityStatus.SUSTAINABLE,
                    utilization=10 / 8,
                    worked=10 * HOUR,
                )
            )

    def test_rejects_bad_fields(self) -> None:
        with pytest.raises(SustainabilityError, match="status must be"):
            Sustainability(**dict(self._kwargs(), status="sustainable"))
        with pytest.raises(SustainabilityError, match="worked must be"):
            Sustainability(**dict(self._kwargs(), worked=-HOUR))
        with pytest.raises(SustainabilityError, match="workable must be"):
            Sustainability(**dict(self._kwargs(), workable="8 hours"))
        with pytest.raises(SustainabilityError, match="max_utilization must be within"):
            Sustainability(**dict(self._kwargs(), max_utilization=2.0))
        with pytest.raises(SustainabilityError, match="utilization must be"):
            Sustainability(**dict(self._kwargs(), utilization="high"))


class TestWiring:
    def test_velocity_feeds_sustainability_and_health(self, plan) -> None:
        """The chain docs/07 implies: sittings → velocity →
        sustainability, alongside the progress reading."""
        from backcasting.domain.goal_health import (
            GoalHealthStatus,
            assess_goal_health,
        )
        from backcasting.domain.progress import take_progress_snapshot
        from backcasting.domain.task import revise_task
        from backcasting.domain.variance import progress_variance

        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        window = create_availability_window(
            calendar, MONDAYS, time(9), time(17), created_at=CREATED
        )
        task = _task(plan)
        task = revise_task(task, duration=10 * HOUR, updated_at=CREATED)
        # A full declared day, then an evening sprint on top.
        executions = (
            _sitting(task, MONDAY, 9, 17),
            _sitting(task, MONDAY, 20, 22),
        )
        at = MONDAY + WEEK
        velocity = _velocity(executions, at=at, window=WEEK)
        reading = assess_sustainability(velocity, (window,))
        snapshot = take_progress_snapshot(plan, (task,), executions, at=at)

        assert reading.status is SustainabilityStatus.UNSUSTAINABLE
        assert reading.worked == 10 * HOUR
        health = assess_goal_health(
            snapshot, variances=(progress_variance(snapshot),)
        )
        # The plan's work is done — healthy progress, an
        # unsustainable way of getting it. Both readings stand.
        assert snapshot.progress == 1.0
        assert health.status is GoalHealthStatus.ON_TRACK
        assert health.reasons == ("plan-complete",)
