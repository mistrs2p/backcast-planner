"""Tests for scheduler integration (TASK-068).

The epic-closing composition: availability → constraints → capacity
→ dependencies → deadline → preferences → splitting → placement,
per task in dependency order, with the docs/06 failure reasons
surfacing at the layer that caused them and the budget consumed by
each placement.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.availability import create_availability_window
from backcasting.domain.calendar import create_calendar
from backcasting.domain.calendar_event import create_event
from backcasting.domain.constraint import create_constraint_weekly
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.preference import (
    PreferenceDirection,
    create_preference,
)
from backcasting.domain.rolling_horizon import operational_horizon
from backcasting.domain.scheduler import (
    FailureReason,
    SchedulerError,
    schedule_tasks,
)
from backcasting.domain.task import create_task
from backcasting.domain.task_dependency import add_dependency
from backcasting.domain.task_estimation import record_estimation

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)


@pytest.fixture
def calendar():
    return create_calendar(uuid.uuid4(), created_at=CREATED)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


@pytest.fixture
def weekdays(calendar):
    """Monday-to-Friday 09:00–17:00 availability."""
    return (
        create_availability_window(
            calendar,
            frozenset(range(5)),
            time(9),
            time(17),
            created_at=CREATED,
        ),
    )


def _task(plan, title, deadline=None):
    return create_task(plan, title, deadline=deadline, created_at=CREATED)


def _estimated(plan, title, hours, deadline=None):
    task = _task(plan, title, deadline=deadline)
    estimation = record_estimation(
        task, timedelta(hours=hours), created_at=CREATED
    )
    return task, estimation


class TestHappyPath:
    def test_single_task_places_in_the_first_free_slot(
        self, plan, weekdays
    ) -> None:
        task, estimation = _estimated(plan, "Draft", 2)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            estimations=(estimation,),
        )
        assert not result.failures
        (placement,) = result.placements
        assert placement.task is task
        (schedule,) = placement.schedules
        assert schedule.start == NOW.replace(hour=9)
        assert schedule.end == NOW.replace(hour=11)

    def test_dependency_places_prerequisite_first(self, plan, weekdays) -> None:
        draft, draft_est = _estimated(plan, "Draft", 2)
        review, review_est = _estimated(plan, "Review", 1)
        links = add_dependency((), review, draft)
        result = schedule_tasks(
            (review, draft),  # input order reversed on purpose
            horizon=operational_horizon(NOW),
            at=NOW,
            dependencies=links,
            windows=weekdays,
            estimations=(draft_est, review_est),
        )
        assert [p.task.task_id for p in result.placements] == [
            draft.task_id,
            review.task_id,
        ]
        review_schedule = result.placements[1].schedules[0]
        assert review_schedule.start >= NOW.replace(hour=11)

    def test_commitment_subtracts_from_candidates(
        self, plan, weekdays, calendar
    ) -> None:
        meeting = create_event(
            calendar, "Meeting", NOW.replace(hour=9), NOW.replace(hour=11),
            created_at=CREATED,
        )
        task, estimation = _estimated(plan, "Work", 2)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            events=(meeting,),
            estimations=(estimation,),
        )
        (schedule,) = result.placements[0].schedules
        assert schedule.start == NOW.replace(hour=11)

    def test_split_task_places_across_days(self, plan, weekdays) -> None:
        """10h does not fit one 8h day: 8h Monday + 2h Tuesday."""
        task, estimation = _estimated(plan, "Big", 10)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            estimations=(estimation,),
        )
        schedules = result.placements[0].schedules
        assert [s.end - s.start for s in schedules] == [8 * HOUR, 2 * HOUR]
        assert schedules[1].start == (NOW + timedelta(days=1)).replace(hour=9)

    def test_preference_ranks_before_splitting(
        self, plan, weekdays, calendar
    ) -> None:
        """An afternoon-avoiding 2h task goes to the morning."""
        avoid_afternoon = create_preference(
            calendar,
            PreferenceDirection.AVOID,
            frozenset(range(5)),
            time(13),
            time(17),
            weight=5,
            created_at=CREATED,
        )
        task, estimation = _estimated(plan, "Focus", 2)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            preferences=(avoid_afternoon,),
            estimations=(estimation,),
        )
        (schedule,) = result.placements[0].schedules
        assert schedule.end <= NOW.replace(hour=13)


class TestFailureReasons:
    def test_no_windows_means_no_available_slot(self, plan) -> None:
        task, estimation = _estimated(plan, "Nowhere", 1)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            estimations=(estimation,),
        )
        assert result.failure_reasons == {FailureReason.NO_AVAILABLE_SLOT}

    def test_hard_constraint_excludes_everything(
        self, plan, weekdays, calendar
    ) -> None:
        all_week = create_constraint_weekly(
            calendar,
            "Sabbatical",
            frozenset(range(5)),
            time(0),
            time(23, 59),
            created_at=CREATED,
        )
        task, estimation = _estimated(plan, "Blocked", 2)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            constraints=(all_week,),
            estimations=(estimation,),
        )
        assert result.failure_reasons == {FailureReason.HARD_CONSTRAINT}

    def test_exhausted_budget_means_no_capacity(self, plan, weekdays) -> None:
        task, estimation = _estimated(plan, "Big", 10)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            estimations=(estimation,),
            budget=5 * HOUR,
        )
        assert result.failure_reasons == {FailureReason.NO_CAPACITY}
        assert result.remaining_budget == 5 * HOUR  # nothing consumed

    def test_unplaced_prerequisite_blocks_the_dependent(
        self, plan, weekdays
    ) -> None:
        draft, draft_est = _estimated(plan, "Draft", 3)
        review, review_est = _estimated(plan, "Review", 1)
        links = add_dependency((), review, draft)
        # Draft cannot fit: two 1-hour Mondays in the horizon cannot
        # absorb 3 hours of work.
        tiny_window = (
            create_availability_window(
                create_calendar(uuid.uuid4(), created_at=CREATED),
                frozenset({0}),
                time(9),
                time(10),
                created_at=CREATED,
            ),
        )
        result = schedule_tasks(
            (draft, review),
            horizon=operational_horizon(NOW),
            at=NOW,
            dependencies=links,
            windows=tiny_window,
            estimations=(draft_est, review_est),
        )
        reasons = {f.task.task_id: f.reason for f in result.failures}
        assert reasons[draft.task_id] is FailureReason.NO_AVAILABLE_SLOT
        assert reasons[review.task_id] is FailureReason.DEPENDENCY_BLOCKED
        assert not result.placements

    def test_candidates_that_cannot_absorb_the_duration(
        self, plan
    ) -> None:
        """2h needed, only two 45-minute Mondays in the horizon."""
        window = (
            create_availability_window(
                create_calendar(uuid.uuid4(), created_at=CREATED),
                frozenset({0}),
                time(9),
                time(9, 45),
                created_at=CREATED,
            ),
        )
        task, estimation = _estimated(plan, "Squeezed", 2)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=window,
            estimations=(estimation,),
        )
        assert result.failure_reasons == {FailureReason.NO_AVAILABLE_SLOT}

    def test_deadline_conflict(self, plan, weekdays) -> None:
        task, estimation = _estimated(
            plan, "Urgent", 2, deadline=NOW.replace(hour=10)
        )
        # The only free time starts at 09:00 but a meeting blocks
        # 09:00–10:00, so nothing can finish by the 10:00 deadline.
        meeting = create_event(
            create_calendar(uuid.uuid4(), created_at=CREATED),
            "Meeting",
            NOW.replace(hour=9),
            NOW.replace(hour=10),
            created_at=CREATED,
        )
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            events=(meeting,),
            estimations=(estimation,),
        )
        assert result.failure_reasons == {FailureReason.DEADLINE_CONFLICT}

    def test_unestimated_task_fails_without_aborting(
        self, plan, weekdays
    ) -> None:
        unestimated = _task(plan, "Mystery")
        task, estimation = _estimated(plan, "Known", 1)
        result = schedule_tasks(
            (unestimated, task),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            estimations=(estimation,),
        )
        assert result.failure_reasons == {FailureReason.UNESTIMATED_TASK}
        assert result.placed_task_ids == {task.task_id}


class TestBudget:
    def test_placements_consume_the_budget_in_order(
        self, plan, weekdays
    ) -> None:
        first, first_est = _estimated(plan, "First", 2)
        second, second_est = _estimated(plan, "Second", 3)
        result = schedule_tasks(
            (first, second),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            estimations=(first_est, second_est),
            budget=10 * HOUR,
        )
        assert not result.failures
        assert result.remaining_budget == 5 * HOUR

    def test_budget_exhaustion_fails_later_tasks(
        self, plan, weekdays
    ) -> None:
        first, first_est = _estimated(plan, "First", 4)
        second, second_est = _estimated(plan, "Second", 4)
        third, third_est = _estimated(plan, "Third", 4)
        result = schedule_tasks(
            (first, second, third),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            estimations=(first_est, second_est, third_est),
            budget=10 * HOUR,
        )
        assert result.placed_task_ids == {first.task_id, second.task_id}
        (failure,) = result.failures
        assert failure.task is third
        assert failure.reason is FailureReason.NO_CAPACITY
        assert result.remaining_budget == 2 * HOUR

    def test_no_budget_means_no_capacity_layer(self, plan, weekdays) -> None:
        task, estimation = _estimated(plan, "Free", 2)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            estimations=(estimation,),
            budget=None,
        )
        assert not result.failures
        assert result.remaining_budget is None


class TestValidation:
    def test_rejects_bad_arguments(self, plan, weekdays) -> None:
        task, estimation = _estimated(plan, "T", 1)
        with pytest.raises(SchedulerError, match="tasks must be a tuple"):
            schedule_tasks(
                [task], horizon=operational_horizon(NOW), at=NOW
            )
        with pytest.raises(SchedulerError, match="horizon must be a Horizon"):
            schedule_tasks((task,), horizon="soon", at=NOW)
        with pytest.raises(SchedulerError, match="at must be"):
            schedule_tasks(
                (task,), horizon=operational_horizon(NOW), at=datetime(2026, 6, 1)
            )
        with pytest.raises(SchedulerError, match="budget must be"):
            schedule_tasks(
                (task,),
                horizon=operational_horizon(NOW),
                at=NOW,
                budget=-HOUR,
            )

    def test_dependency_cycle_propagates(self, plan, weekdays) -> None:
        from backcasting.domain.task_dependency import TaskDependency, TaskDependencyError

        a, a_est = _estimated(plan, "A", 1)
        b, b_est = _estimated(plan, "B", 1)
        # add_dependency refuses cycles at construction; the raw
        # records model a persisted-but-corrupt link set.
        links = (
            TaskDependency(task_id=a.task_id, depends_on_task_id=b.task_id),
            TaskDependency(task_id=b.task_id, depends_on_task_id=a.task_id),
        )
        with pytest.raises(TaskDependencyError):
            schedule_tasks(
                (a, b),
                horizon=operational_horizon(NOW),
                at=NOW,
                dependencies=links,
                windows=weekdays,
                estimations=(a_est, b_est),
            )

    def test_off_granularity_estimate_raises(self, plan, weekdays) -> None:
        task = _task(plan, "Odd")
        estimation = record_estimation(
            task, timedelta(minutes=50), created_at=CREATED
        )
        from backcasting.domain.task_splitting import TaskSplittingError

        with pytest.raises(TaskSplittingError, match="granularity"):
            schedule_tasks(
                (task,),
                horizon=operational_horizon(NOW),
                at=NOW,
                windows=weekdays,
                estimations=(estimation,),
            )


class TestWiring:
    def test_rolling_horizon_feeds_the_scheduler(
        self, plan, weekdays
    ) -> None:
        """Only the exact partition is scheduled; the approximate
        task stays out of the pipeline entirely."""
        from backcasting.domain.rolling_horizon import split_tasks_by_horizon

        due, due_est = _estimated(
            plan, "Due", 1, deadline=NOW + timedelta(days=1)
        )
        far, _ = _estimated(plan, "Far", 1, deadline=NOW + timedelta(weeks=4))
        split = split_tasks_by_horizon(
            (due, far), (), (), (), horizon=operational_horizon(NOW)
        )
        result = schedule_tasks(
            split.exact,
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            estimations=(due_est,),
        )
        assert result.placed_task_ids == {due.task_id}
        assert far.task_id not in result.placed_task_ids

    def test_result_feeds_conflict_resolution_later(
        self, plan, weekdays, calendar
    ) -> None:
        """A later commitment displaces a persisted placement."""
        from backcasting.domain.conflict_resolution import (
            displace_for_commitments,
            resolve_displacement,
            ResolutionAction,
        )

        task, estimation = _estimated(plan, "Work", 2)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=weekdays,
            estimations=(estimation,),
        )
        schedules = result.placements[0].schedules
        meeting = create_event(
            calendar, "Meeting", NOW.replace(hour=10), NOW.replace(hour=12),
            created_at=CREATED,
        )
        (displacement,) = displace_for_commitments(schedules, (meeting,))
        resolution = resolve_displacement(
            displacement.schedule, ()
        )  # nothing survives — just checking the hand-off shape
        assert resolution.action is ResolutionAction.ESCALATE_TO_REPLANNING

    def test_timezone_anchored_availability(self, plan) -> None:
        """A Tokyo 09:00–17:00 window is 00:00–08:00 UTC."""
        tokyo = ZoneInfo("Asia/Tokyo")
        calendar = create_calendar(
            uuid.uuid4(), timezone=tokyo, created_at=CREATED
        )
        window = (
            create_availability_window(
                calendar,
                frozenset(range(7)),
                time(9),
                time(17),
                timezone=tokyo,
                created_at=CREATED,
            ),
        )
        task, estimation = _estimated(plan, "Tokyo work", 2)
        result = schedule_tasks(
            (task,),
            horizon=operational_horizon(NOW),
            at=NOW,
            windows=window,
            estimations=(estimation,),
        )
        (schedule,) = result.placements[0].schedules
        assert schedule.start == NOW  # Monday 00:00 UTC = Tokyo 09:00
