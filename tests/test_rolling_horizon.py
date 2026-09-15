"""Tests for the rolling horizon (TASK-067).

Pins docs/06's shape — "Long-term: milestones/approximate
allocation. Short-term: exact tasks and slots. Default operational
horizon: next 2 weeks." The window is [now, now + 2 weeks); what it
exacts: due tasks (overdue counts), near-milestone outcome tasks,
and their prerequisite chains. Everything else stays approximate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.backcasting_run import start_run
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.milestone import define_milestone
from backcasting.domain.outcome import define_outcome
from backcasting.domain.plan import create_plan
from backcasting.domain.rolling_horizon import (
    DEFAULT_HORIZON,
    Horizon,
    HorizonSplit,
    RollingHorizonError,
    operational_horizon,
    split_tasks_by_horizon,
)
from backcasting.domain.task import create_task, serve_outcomes
from backcasting.domain.task_dependency import add_dependency

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
CALCULATED = datetime(2026, 1, 6, tzinfo=timezone.utc)
STARTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)


@pytest.fixture
def running_run():
    goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
    current = capture_current_state(
        goal.goal_id, "Can run 5 km.", captured_at=CAPTURED
    )
    future = define_future_state(
        goal.goal_id,
        "Complete the marathon.",
        datetime(2026, 10, 11, tzinfo=timezone.utc),
        created_at=CREATED,
    )
    gap = calculate_gap(goal, current, future, calculated_at=CALCULATED)
    return start_run(goal, current, future, gap, started_at=STARTED)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, title, deadline=None):
    return create_task(plan, title, deadline=deadline, created_at=CREATED)


class TestOperationalHorizon:
    def test_default_horizon_is_two_weeks(self) -> None:
        horizon = operational_horizon(NOW)
        assert horizon.duration == DEFAULT_HORIZON == timedelta(weeks=2)
        assert horizon.start == NOW
        assert horizon.end == NOW + timedelta(weeks=2)

    def test_custom_duration(self) -> None:
        horizon = operational_horizon(NOW, duration=timedelta(days=3))
        assert horizon.end == NOW + timedelta(days=3)

    def test_window_is_half_open(self) -> None:
        horizon = operational_horizon(NOW)
        assert horizon.contains(NOW)
        assert horizon.contains(horizon.end - HOUR)
        assert not horizon.contains(horizon.end)

    def test_rolling_rederives_from_the_instant(self) -> None:
        first = operational_horizon(NOW)
        later = operational_horizon(NOW + timedelta(days=7))
        assert later.start == first.start + timedelta(days=7)
        assert later.end == first.end + timedelta(days=7)

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(RollingHorizonError, match="now must be"):
            operational_horizon(datetime(2026, 6, 1))
        with pytest.raises(RollingHorizonError, match="strictly positive"):
            operational_horizon(NOW, duration=timedelta(0))

    def test_horizon_record_validates_itself(self) -> None:
        with pytest.raises(RollingHorizonError, match="end must be after start"):
            Horizon(start=NOW, end=NOW)
        with pytest.raises(RollingHorizonError, match="start must be"):
            Horizon(start=datetime(2026, 6, 1), end=NOW)


class TestSplitTasksByHorizon:
    def test_task_due_inside_the_horizon_is_exact(self, plan) -> None:
        due = _task(plan, "Due", deadline=NOW + timedelta(days=3))
        far = _task(plan, "Far", deadline=NOW + timedelta(weeks=4))
        split = split_tasks_by_horizon(
            (due, far), (), (), (), horizon=operational_horizon(NOW)
        )
        assert split.exact == (due,)
        assert split.approximate == (far,)

    def test_task_without_deadline_is_approximate(self, plan) -> None:
        task = _task(plan, "Someday")
        split = split_tasks_by_horizon(
            (task,), (), (), (), horizon=operational_horizon(NOW)
        )
        assert split == HorizonSplit(exact=(), approximate=(task,))

    def test_overdue_deadline_is_due(self, plan) -> None:
        overdue = _task(plan, "Late", deadline=NOW - timedelta(days=1))
        split = split_tasks_by_horizon(
            (overdue,), (), (), (), horizon=operational_horizon(NOW)
        )
        assert split.exact == (overdue,)

    def test_deadline_exactly_at_the_end_is_exact(self, plan) -> None:
        boundary = _task(plan, "Boundary", deadline=NOW + timedelta(weeks=2))
        split = split_tasks_by_horizon(
            (boundary,), (), (), (), horizon=operational_horizon(NOW)
        )
        assert split.exact == (boundary,)

    def test_near_milestone_pulls_its_outcome_tasks(
        self, plan, running_run
    ) -> None:
        milestone = define_milestone(
            running_run,
            "Checkpoint",
            NOW + timedelta(days=5),
            created_at=STARTED + timedelta(minutes=5),
        )
        outcome = define_outcome(plan, "Shipped", milestone=milestone,
                                 created_at=CREATED)
        anchored = serve_outcomes(
            _task(plan, "Anchored"), (outcome,), updated_at=CREATED
        )
        split = split_tasks_by_horizon(
            (anchored,), (), (milestone,), (outcome,),
            horizon=operational_horizon(NOW),
        )
        assert split.exact == (anchored,)

    def test_far_milestone_does_not_pull(
        self, plan, running_run
    ) -> None:
        milestone = define_milestone(
            running_run,
            "Far checkpoint",
            NOW + timedelta(weeks=6),
            created_at=STARTED + timedelta(minutes=5),
        )
        outcome = define_outcome(plan, "Later", milestone=milestone,
                                 created_at=CREATED)
        anchored = serve_outcomes(
            _task(plan, "Anchored"), (outcome,), updated_at=CREATED
        )
        split = split_tasks_by_horizon(
            (anchored,), (), (milestone,), (outcome,),
            horizon=operational_horizon(NOW),
        )
        assert split.approximate == (anchored,)

    def test_outcome_without_milestone_does_not_pull(self, plan) -> None:
        outcome = define_outcome(plan, "Loose", created_at=CREATED)
        task = serve_outcomes(
            _task(plan, "Serving"), (outcome,), updated_at=CREATED
        )
        split = split_tasks_by_horizon(
            (task,), (), (), (outcome,), horizon=operational_horizon(NOW)
        )
        assert split.approximate == (task,)

    def test_prerequisites_of_exact_tasks_are_exact(self, plan) -> None:
        final = _task(plan, "Final", deadline=NOW + timedelta(days=3))
        middle = _task(plan, "Middle")
        first = _task(plan, "First")
        links = add_dependency(add_dependency((), final, middle), middle, first)
        split = split_tasks_by_horizon(
            (first, middle, final), links, (), (),
            horizon=operational_horizon(NOW),
        )
        assert split.exact == (first, middle, final)

    def test_prerequisites_of_approximate_tasks_stay_approximate(
        self, plan
    ) -> None:
        a = _task(plan, "A")
        b = _task(plan, "B")
        links = add_dependency((), b, a)
        split = split_tasks_by_horizon(
            (a, b), links, (), (), horizon=operational_horizon(NOW)
        )
        assert split.approximate == (a, b)

    def test_partitions_preserve_input_order(self, plan) -> None:
        far = _task(plan, "Far", deadline=NOW + timedelta(weeks=4))
        due = _task(plan, "Due", deadline=NOW + timedelta(days=1))
        also_far = _task(plan, "Also far")
        split = split_tasks_by_horizon(
            (far, due, also_far), (), (), (), horizon=operational_horizon(NOW)
        )
        assert split.exact == (due,)
        assert split.approximate == (far, also_far)

    def test_empty_tasks_split_empty(self) -> None:
        split = split_tasks_by_horizon(
            (), (), (), (), horizon=operational_horizon(NOW)
        )
        assert split == HorizonSplit(exact=(), approximate=())

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan, "T")
        with pytest.raises(RollingHorizonError, match="horizon must be a Horizon"):
            split_tasks_by_horizon((task,), (), (), (), horizon="soon")
        with pytest.raises(RollingHorizonError, match="tasks must be a tuple"):
            split_tasks_by_horizon(
                [task], (), (), (), horizon=operational_horizon(NOW)
            )
        with pytest.raises(RollingHorizonError, match="Task instances"):
            split_tasks_by_horizon(
                ("x",), (), (), (), horizon=operational_horizon(NOW)
            )
        with pytest.raises(RollingHorizonError, match="unique ids"):
            split_tasks_by_horizon(
                (task, task), (), (), (), horizon=operational_horizon(NOW)
            )
        with pytest.raises(RollingHorizonError, match="milestones must be a tuple"):
            split_tasks_by_horizon(
                (task,), (), [], (), horizon=operational_horizon(NOW)
            )
        with pytest.raises(RollingHorizonError, match="outcomes must be a tuple"):
            split_tasks_by_horizon(
                (task,), (), (), [], horizon=operational_horizon(NOW)
            )


class TestWiring:
    def test_exact_tasks_feed_the_scheduling_pipeline(self, plan) -> None:
        """Only the exact partition goes to slot generation."""
        from backcasting.domain.candidate_slot import generate_candidate_slots

        due = _task(plan, "Due", deadline=NOW + timedelta(days=1))
        far = _task(plan, "Far", deadline=NOW + timedelta(weeks=4))
        split = split_tasks_by_horizon(
            (due, far), (), (), (), horizon=operational_horizon(NOW)
        )
        slots = generate_candidate_slots(
            (), events=(), duration=HOUR,
            range_start=NOW, range_end=NOW + timedelta(days=1),
        )
        assert slots == ()
        assert split.exact == (due,)  # the pipeline's input

    def test_horizon_rolls_tasks_into_the_exact_zone(self, plan) -> None:
        """A task four weeks out becomes exact as the window rolls."""
        task = _task(plan, "Approaching", deadline=NOW + timedelta(weeks=4))
        early = split_tasks_by_horizon(
            (task,), (), (), (), horizon=operational_horizon(NOW)
        )
        later = split_tasks_by_horizon(
            (task,), (), (), (),
            horizon=operational_horizon(NOW + timedelta(weeks=3)),
        )
        assert early.approximate == (task,)
        assert later.exact == (task,)
