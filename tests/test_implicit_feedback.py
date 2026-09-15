"""Tests for implicit feedback (TASK-078).

"Implicit behavioral signals" (docs/07): mechanically derived from
the behavior records, stated as factual sentences, returned only
when the behavior is present.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from backcasting.domain.availability import create_availability_window
from backcasting.domain.calendar import create_calendar
from backcasting.domain.calendar_event import create_event
from backcasting.domain.execution import create_execution
from backcasting.domain.feedback import (
    Feedback,
    FeedbackError,
    FeedbackKind,
    detect_work_outside_availability,
    detect_work_outside_placements,
)
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.schedule import create_schedule
from backcasting.domain.task import create_task, revise_task

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
MONDAYS = frozenset({0})


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


class TestDetectWorkOutsideAvailability:
    @pytest.fixture
    def calendar(self):
        return create_calendar(uuid.uuid4(), created_at=CREATED)

    @pytest.fixture
    def nine_to_five(self, calendar):
        return create_availability_window(
            calendar, MONDAYS, time(9), time(17), created_at=CREATED
        )

    def test_work_inside_the_windows_is_not_a_signal(
        self, plan, nine_to_five
    ) -> None:
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 9, 17),)
        assert (
            detect_work_outside_availability(
                executions, (nine_to_five,), at=MONDAY + timedelta(days=1)
            )
            is None
        )

    def test_work_outside_the_windows_is_a_signal(self, plan, nine_to_five) -> None:
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 19, 21),)
        signal = detect_work_outside_availability(
            executions, (nine_to_five,), at=MONDAY + timedelta(days=1)
        )
        assert signal is not None
        assert signal.kind is FeedbackKind.IMPLICIT
        assert signal.created_at == MONDAY + timedelta(days=1)
        assert "2:00:00" in signal.statement
        assert "outside the declared availability" in signal.statement

    def test_partial_overlap_counts_only_the_outside_part(
        self, plan, nine_to_five
    ) -> None:
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 15, 19),)  # 2h in, 2h out
        signal = detect_work_outside_availability(
            executions, (nine_to_five,), at=MONDAY + timedelta(days=1)
        )
        assert signal is not None
        assert "2:00:00" in signal.statement

    def test_work_during_commitments_is_outside(self, plan, calendar, nine_to_five) -> None:
        """Workable is availability minus commitments; working
        through a commitment is outside the workable time."""
        task = _task(plan)
        meeting = create_event(
            calendar, "All-hands", MONDAY.replace(hour=9), MONDAY.replace(hour=11),
            created_at=CREATED,
        )
        executions = (_sitting(task, MONDAY, 9, 11),)
        signal = detect_work_outside_availability(
            executions, (nine_to_five,), (meeting,), at=MONDAY + timedelta(days=1)
        )
        assert signal is not None
        assert "2:00:00" in signal.statement

    def test_no_executions_is_not_a_signal(self, nine_to_five) -> None:
        assert (
            detect_work_outside_availability(
                (), (nine_to_five,), at=MONDAY
            )
            is None
        )

    def test_rejects_bad_arguments(self, plan, nine_to_five) -> None:
        task = _task(plan)
        with pytest.raises(FeedbackError, match="executions must be a tuple"):
            detect_work_outside_availability(
                [], (nine_to_five,), at=MONDAY
            )
        with pytest.raises(FeedbackError, match="Execution instances"):
            detect_work_outside_availability(
                ("x",), (nine_to_five,), at=MONDAY
            )
        with pytest.raises(FeedbackError, match="windows must be a tuple"):
            detect_work_outside_availability((), [], at=MONDAY)
        with pytest.raises(FeedbackError, match="events must be a tuple"):
            detect_work_outside_availability((), (nine_to_five,), [], at=MONDAY)
        with pytest.raises(FeedbackError, match="at must be"):
            detect_work_outside_availability((), (), at=datetime(2026, 6, 1))


class TestDetectWorkOutsidePlacements:
    def test_work_on_the_placement_is_not_a_signal(self, plan) -> None:
        task = _task(plan, 2)
        schedule = create_schedule(
            task, MONDAY.replace(hour=9), MONDAY.replace(hour=11), created_at=CREATED
        )
        executions = (_sitting(task, MONDAY, 9, 11),)
        assert (
            detect_work_outside_placements(
                executions, (schedule,), at=MONDAY + timedelta(days=1)
            )
            is None
        )

    def test_work_off_the_placement_is_a_signal(self, plan) -> None:
        task = _task(plan, 2)
        schedule = create_schedule(
            task, MONDAY.replace(hour=9), MONDAY.replace(hour=11), created_at=CREATED
        )
        executions = (_sitting(task, MONDAY, 15, 17),)
        signal = detect_work_outside_placements(
            executions, (schedule,), at=MONDAY + timedelta(days=1)
        )
        assert signal is not None
        assert signal.kind is FeedbackKind.IMPLICIT
        assert "2:00:00" in signal.statement
        assert "outside the placed times" in signal.statement

    def test_straddling_counts_only_the_outside_part(self, plan) -> None:
        task = _task(plan, 4)
        schedule = create_schedule(
            task, MONDAY.replace(hour=10), MONDAY.replace(hour=12), created_at=CREATED
        )
        executions = (_sitting(task, MONDAY, 9, 13),)  # 2h in, 2h out
        signal = detect_work_outside_placements(
            executions, (schedule,), at=MONDAY + timedelta(days=1)
        )
        assert signal is not None
        assert "2:00:00" in signal.statement

    def test_unscheduled_tasks_are_ignored(self, plan) -> None:
        """A task with no placement has no placed time to be outside
        of — that absence is a planning concern, not a behavioral one."""
        unscheduled = _task(plan)
        other = _task(plan, 2)
        schedule = create_schedule(
            other, MONDAY.replace(hour=9), MONDAY.replace(hour=11), created_at=CREATED
        )
        executions = (
            _sitting(unscheduled, MONDAY, 13, 15),  # no placement: ignored
            _sitting(other, MONDAY, 9, 11),          # on placement
        )
        assert (
            detect_work_outside_placements(
                executions, (schedule,), at=MONDAY + timedelta(days=1)
            )
            is None
        )

    def test_split_placements_cover_split_work(self, plan) -> None:
        task = _task(plan, 4)
        schedules = (
            create_schedule(
                task, MONDAY.replace(hour=9), MONDAY.replace(hour=11),
                created_at=CREATED,
            ),
            create_schedule(
                task, MONDAY.replace(hour=14), MONDAY.replace(hour=16),
                created_at=CREATED,
            ),
        )
        executions = (
            _sitting(task, MONDAY, 9, 11),
            _sitting(task, MONDAY, 15, 17),  # half in the afternoon placement
        )
        signal = detect_work_outside_placements(
            executions, schedules, at=MONDAY + timedelta(days=1)
        )
        assert signal is not None
        assert "1:00:00" in signal.statement

    def test_nothing_scheduled_is_not_a_signal(self, plan) -> None:
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 9, 17),)
        assert (
            detect_work_outside_placements(executions, (), at=MONDAY) is None
        )

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan)
        schedule = create_schedule(
            task, MONDAY.replace(hour=9), MONDAY.replace(hour=11), created_at=CREATED
        )
        with pytest.raises(FeedbackError, match="executions must be a tuple"):
            detect_work_outside_placements([], (schedule,), at=MONDAY)
        with pytest.raises(FeedbackError, match="Execution instances"):
            detect_work_outside_placements(("x",), (schedule,), at=MONDAY)
        with pytest.raises(FeedbackError, match="schedules must be a tuple"):
            detect_work_outside_placements((), [], at=MONDAY)
        with pytest.raises(FeedbackError, match="Schedule instances"):
            detect_work_outside_placements((), ("x",), at=MONDAY)
        with pytest.raises(FeedbackError, match="at must be"):
            detect_work_outside_placements((), (), at=datetime(2026, 6, 1))


class TestWiring:
    def test_evening_sprint_yields_both_signals(self, plan) -> None:
        """One behavior record set, two implicit signals, and the
        sustainability reading that agrees with them."""
        from backcasting.domain.sustainability import (
            SustainabilityStatus,
            assess_sustainability,
        )
        from backcasting.domain.velocity import compute_velocity

        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        window = create_availability_window(
            calendar, MONDAYS, time(9), time(17), created_at=CREATED
        )
        task = _task(plan, 10)
        schedule = create_schedule(
            task, MONDAY.replace(hour=9), MONDAY.replace(hour=17), created_at=CREATED
        )
        # The declared day was placed and worked; then an evening sprint.
        executions = (
            _sitting(task, MONDAY, 9, 17),
            _sitting(task, MONDAY, 20, 22),
        )
        at = MONDAY + timedelta(days=7)

        outside_availability = detect_work_outside_availability(
            executions, (window,), at=at
        )
        outside_placements = detect_work_outside_placements(
            executions, (schedule,), at=at
        )
        reading = assess_sustainability(
            compute_velocity(executions, at=at, window=timedelta(days=7)), (window,)
        )

        assert outside_availability is not None
        assert "2:00:00" in outside_availability.statement
        assert outside_placements is not None
        assert "2:00:00" in outside_placements.statement
        assert reading.status is SustainabilityStatus.UNSUSTAINABLE

    def test_signals_are_ordinary_feedback_records(self, plan) -> None:
        """Derived signals share the record: they store, filter, and
        travel like explicit statements."""
        from backcasting.domain.feedback import feedback_for_subject

        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        window = create_availability_window(
            calendar, MONDAYS, time(9), time(17), created_at=CREATED
        )
        task = _task(plan)
        executions = (_sitting(task, MONDAY, 20, 22),)
        signal = detect_work_outside_availability(
            executions, (window,), at=MONDAY
        )
        explicit = Feedback(
            feedback_id=uuid.uuid4(),
            kind=FeedbackKind.EXPLICIT,
            statement="I know, I worked late.",
            created_at=MONDAY,
        )
        assert isinstance(signal, Feedback)
        assert feedback_for_subject((signal, explicit), uuid.uuid4()) == ()
        assert {signal.kind, explicit.kind} == {FeedbackKind.IMPLICIT, FeedbackKind.EXPLICIT}
