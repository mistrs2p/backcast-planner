"""Capacity epic integration tests (TASK-046).

Pins EPIC-005 end to end: a realistic calendar environment — weekly
availability, a recurring commitment with exceptions, hard constraints
— measured history, buffer, and the capacity pool, all composed by
``analyze_time_environment`` and fed into ``execute_backcasting``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.availability import create_availability_window
from backcasting.domain.backcasting import (
    InfeasibleBackcasting,
    execute_backcasting,
)
from backcasting.domain.backcasting_run import BackcastingRunStatus
from backcasting.domain.buffer import create_buffer
from backcasting.domain.calendar import create_calendar
from backcasting.domain.calendar_event import create_event
from backcasting.domain.capacity_analysis import analyze_time_environment
from backcasting.domain.capacity_pool import (
    CapacityAllocation,
    allocate_capacity,
)
from backcasting.domain.constraint import create_constraint_range
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.effective_capacity import (
    CapacitySample,
    EffectiveCapacity,
)
from backcasting.domain.future_state import define_future_state
from backcasting.domain.goal import create_goal
from backcasting.domain.metric import Metric, MetricDirection, MetricKind
from backcasting.domain.milestone import MilestoneProposal
from backcasting.domain.observed_capacity import measure_observed_capacity
from backcasting.domain.planned_capacity import (
    derive_planned_capacity,
    workable_time,
)
from backcasting.domain.recurrence import Frequency, create_rule, expand_rule
from backcasting.domain.recurrence_exception import (
    cancel_occurrence,
    expand_with_exceptions,
    reschedule_occurrence,
)
from backcasting.domain.strategy import StrategyProposal

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
EXECUTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)
BETA = datetime(2026, 8, 1, tzinfo=timezone.utc)
UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")

# 2026-06-01 is a Monday.
WEEK_START = datetime(2026, 6, 1, tzinfo=UTC)
WEEK_END = WEEK_START + timedelta(days=7)
PREV_WEEK_START = WEEK_START - timedelta(days=7)
PREV_WEEK_END = WEEK_START
HOUR = timedelta(hours=1)
HALF_HOUR = timedelta(minutes=30)
WEDNESDAY_STANDUP = WEEK_START + timedelta(days=2, hours=9, minutes=30)

# The days around the 2026-03-29 London spring-forward.
DST_DAY_START = datetime(2026, 3, 29, tzinfo=UTC)
DST_DAY_END = DST_DAY_START + timedelta(days=1)
PLAIN_DAY_START = datetime(2026, 3, 22, tzinfo=UTC)
PLAIN_DAY_END = PLAIN_DAY_START + timedelta(days=1)


@pytest.fixture
def calendar():
    return create_calendar(uuid.uuid4(), created_at=CREATED)


@pytest.fixture
def weekday_windows(calendar):
    # Monday–Friday 09:00–17:00 UTC: 40 hours over the week.
    return (
        create_availability_window(
            calendar, {0, 1, 2, 3, 4}, time(9), time(17), created_at=CREATED
        ),
    )


def _standup_rule(calendar):
    # Monday–Friday 09:30 UTC, 30 minutes each.
    return create_rule(
        calendar,
        "Standup",
        Frequency.WEEKLY,
        WEEK_START + timedelta(hours=9, minutes=30),
        HALF_HOUR,
        by_weekday={0, 1, 2, 3, 4},
        created_at=CREATED,
    )


def _expand(calendar, rule, exceptions=()):
    return expand_with_exceptions(
        rule, calendar, exceptions, window_start=WEEK_START, window_end=WEEK_END
    )


def _monday_block(calendar):
    # Monday 14:00–16:00 UTC: two hard-blocked hours of availability.
    return create_constraint_range(
        calendar,
        "Focus block",
        WEEK_START + timedelta(hours=14),
        WEEK_START + timedelta(hours=16),
        created_at=CREATED,
    )


def _history_sample(calendar, weekday_windows) -> CapacitySample:
    """Last week: 40h planned, 30h actually delivered."""
    planned = derive_planned_capacity(
        calendar,
        weekday_windows,
        range_start=PREV_WEEK_START,
        range_end=PREV_WEEK_END,
        created_at=CREATED,
    )
    # Ten hours of last week's availability were consumed by reality:
    # five on Monday, five on Tuesday, both inside the windows.
    consumed = (
        create_event(
            calendar,
            "Retrospective",
            PREV_WEEK_START + timedelta(hours=10),
            PREV_WEEK_START + timedelta(hours=15),
            created_at=CREATED,
        ),
        create_event(
            calendar,
            "Planning",
            PREV_WEEK_START + timedelta(days=1, hours=9),
            PREV_WEEK_START + timedelta(days=1, hours=14),
            created_at=CREATED,
        ),
    )
    observed = measure_observed_capacity(
        calendar,
        weekday_windows,
        consumed,
        range_start=PREV_WEEK_START,
        range_end=PREV_WEEK_END,
        measured_at=PREV_WEEK_END,
    )
    assert planned.amount == 40 * HOUR
    assert observed.amount == 30 * HOUR
    return CapacitySample(planned=planned, observed=observed)


def _analyze(calendar, weekday_windows, events, constraints, **kwargs):
    return analyze_time_environment(
        calendar,
        weekday_windows,
        events,
        constraints,
        period_start=WEEK_START,
        period_end=WEEK_END,
        created_at=CREATED,
        **kwargs,
    )


def _goal_context():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    current = capture_current_state(
        goal.goal_id, "Feature half-done.", captured_at=CAPTURED
    )
    future = define_future_state(
        goal.goal_id, "Feature shipped.", TARGET, created_at=CREATED
    )
    return goal, current, future


class TestFullPipeline:
    def test_environment_feeds_backcasting_end_to_end(
        self, calendar, weekday_windows
    ) -> None:
        rule = _standup_rule(calendar)
        events = _expand(
            calendar,
            rule,
            (cancel_occurrence(rule, WEDNESDAY_STANDUP, created_at=CREATED),),
        )
        analysis = _analyze(
            calendar,
            weekday_windows,
            events,
            (_monday_block(calendar),),
            history=(_history_sample(calendar, weekday_windows),),
            buffer=create_buffer(
                calendar,
                0.1,
                period_start=WEEK_START,
                period_end=WEEK_END,
                created_at=CREATED,
            ),
        )
        # 40h availability − 2h constrained − 2h occupying standups.
        assert analysis.planned_amount == 36 * HOUR
        # History delivered 30 of 40 planned → trust 75%.
        assert analysis.effective_amount == 27 * HOUR
        assert analysis.reserved_amount == timedelta(hours=2.7)
        assert analysis.usable_amount == timedelta(hours=24, minutes=18)

        goal, current, future = _goal_context()
        result = execute_backcasting(
            goal,
            current,
            future,
            ((Metric("Bugs", MetricKind.COUNT, MetricDirection.MINIMIZE), 12, 0),),
            required_workload=20 * HOUR,
            buffer=analysis.reserved_amount,
            usable_capacity=analysis.usable_amount,
            strategy_proposals=(StrategyProposal("Focus week"),),
            selected_strategy_name="Focus week",
            milestone_proposals=(MilestoneProposal("Beta", BETA),),
            at=EXECUTED,
        )
        assert result.run.status is BackcastingRunStatus.COMPLETED
        assert result.feasibility.feasible
        assert result.feasibility.usable_capacity == analysis.usable_amount
        assert result.feasibility.buffer == analysis.reserved_amount

    def test_overcommitted_environment_fails_backcasting(
        self, calendar, weekday_windows
    ) -> None:
        rule = _standup_rule(calendar)
        events = _expand(calendar, rule)
        analysis = _analyze(
            calendar,
            weekday_windows,
            events,
            (_monday_block(calendar),),
            history=(_history_sample(calendar, weekday_windows),),
        )
        assert analysis.usable_amount == timedelta(hours=26.625)  # 35.5h × 0.75

        goal, current, future = _goal_context()
        with pytest.raises(InfeasibleBackcasting) as excinfo:
            execute_backcasting(
                goal,
                current,
                future,
                (
                    (
                        Metric("Bugs", MetricKind.COUNT, MetricDirection.MINIMIZE),
                        12,
                        0,
                    ),
                ),
                required_workload=30 * HOUR,  # 30h > 25.5h usable
                buffer=timedelta(0),
                usable_capacity=analysis.usable_amount,
                strategy_proposals=(StrategyProposal("Focus week"),),
                selected_strategy_name="Focus week",
                milestone_proposals=(MilestoneProposal("Beta", BETA),),
                at=EXECUTED,
            )
        assert excinfo.value.run.status is BackcastingRunStatus.FAILED
        assert not excinfo.value.feasibility.feasible
        assert excinfo.value.feasibility.usable_capacity == analysis.usable_amount


class TestRecurrenceExceptionsChangeCapacity:
    def test_cancelled_occurrence_frees_capacity(
        self, calendar, weekday_windows
    ) -> None:
        rule = _standup_rule(calendar)
        constraints = (_monday_block(calendar),)
        with_all = _analyze(
            calendar, weekday_windows, _expand(calendar, rule), constraints
        )
        with_cancel = _analyze(
            calendar,
            weekday_windows,
            _expand(
                calendar,
                rule,
                (cancel_occurrence(rule, WEDNESDAY_STANDUP, created_at=CREATED),),
            ),
            constraints,
        )
        assert with_all.planned_amount + HALF_HOUR == with_cancel.planned_amount
        assert with_all.occupying_amount == with_cancel.occupying_amount + HALF_HOUR
        # The cancelled standup is gone entirely, not just moved.
        assert with_all.commitment_amount == with_cancel.commitment_amount + HALF_HOUR

    def test_rescheduled_occurrence_moves_the_bite(
        self, calendar, weekday_windows
    ) -> None:
        rule = _standup_rule(calendar)
        saturday = WEEK_START + timedelta(days=5, hours=10, minutes=30)
        rescheduled = _analyze(
            calendar,
            weekday_windows,
            _expand(
                calendar,
                rule,
                (
                    reschedule_occurrence(
                        rule, WEDNESDAY_STANDUP, saturday, created_at=CREATED
                    ),
                ),
            ),
            (),
        )
        baseline = _analyze(calendar, weekday_windows, _expand(calendar, rule), ())
        # Same total commitment time, but Saturday's copy lands outside
        # the windows — so it stops consuming capacity.
        assert rescheduled.commitment_amount == baseline.commitment_amount
        assert rescheduled.occupying_amount == baseline.occupying_amount - HALF_HOUR
        assert rescheduled.planned_amount == baseline.planned_amount + HALF_HOUR


class TestPoolIntegration:
    def test_pool_splits_the_analysis_effective_capacity(
        self, calendar, weekday_windows
    ) -> None:
        analysis = _analyze(
            calendar,
            weekday_windows,
            (),
            (),
            history=(_history_sample(calendar, weekday_windows),),
        )
        effective = EffectiveCapacity(
            capacity_id=uuid.uuid4(),
            calendar_id=calendar.calendar_id,
            period_start=WEEK_START,
            period_end=WEEK_END,
            amount=analysis.effective_amount,
            planned_amount=analysis.planned_amount,
            observed_amount=30 * HOUR,
            sample_count=analysis.sample_count,
            created_at=CREATED,
            updated_at=CREATED,
        )
        goal_a, goal_b = uuid.uuid4(), uuid.uuid4()
        pool = allocate_capacity(
            effective,
            (
                CapacityAllocation(goal_a, 10 * HOUR),
                CapacityAllocation(goal_b, 5 * HOUR),
            ),
            created_at=CREATED,
        )
        assert pool.effective_amount == analysis.effective_amount
        assert pool.allocated_amount == 15 * HOUR
        assert pool.unallocated_amount == 15 * HOUR
        assert pool.allocation_for(goal_a) == 10 * HOUR
        assert pool.allocation_for(goal_b) == 5 * HOUR


class TestDstEndToEnd:
    def test_spring_forward_loses_a_capacity_hour(self) -> None:
        # A Sunday 00:00–04:00 local window on a London calendar.
        tz_calendar = create_calendar(
            uuid.uuid4(), timezone=LONDON, created_at=CREATED
        )
        window = create_availability_window(
            tz_calendar, {6}, time(0), time(4), created_at=CREATED
        )
        plain = analyze_time_environment(
            tz_calendar,
            (window,),
            (),
            (),
            period_start=PLAIN_DAY_START,
            period_end=PLAIN_DAY_END,
            created_at=CREATED,
        )
        transition = analyze_time_environment(
            tz_calendar,
            (window,),
            (),
            (),
            period_start=DST_DAY_START,
            period_end=DST_DAY_END,
            created_at=CREATED,
        )
        # A plain Sunday yields four hours; the 2026-03-29 spring
        # forward eats 01:00–02:00 local, leaving three.
        assert plain.availability_amount == 4 * HOUR
        assert transition.availability_amount == 3 * HOUR


class TestConsistencyWithUnitSemantics:
    def test_analysis_planned_matches_workable_time(
        self, calendar, weekday_windows
    ) -> None:
        rule = _standup_rule(calendar)
        events = _expand(calendar, rule)
        analysis = _analyze(calendar, weekday_windows, events, ())
        assert analysis.planned_amount == workable_time(
            weekday_windows, events, range_start=WEEK_START, range_end=WEEK_END
        )
        # And the TASK-038 record derivation agrees when no constraint
        # blocks availability.
        record = derive_planned_capacity(
            calendar,
            weekday_windows,
            events,
            range_start=WEEK_START,
            range_end=WEEK_END,
        )
        assert analysis.planned_amount == record.amount

    def test_analysis_amounts_never_exceed_availability(
        self, calendar, weekday_windows
    ) -> None:
        rule = _standup_rule(calendar)
        events = _expand(calendar, rule)
        constraints = (
            _monday_block(calendar),
            create_constraint_range(
                calendar,
                "Late block",
                WEEK_START + timedelta(hours=16),
                WEEK_START + timedelta(hours=20),
                created_at=CREATED,
            ),
        )
        analysis = _analyze(calendar, weekday_windows, events, constraints)
        assert analysis.availability_amount == 40 * HOUR
        # Monday 14:00–16:00 and 16:00–17:00 both sit on availability.
        assert analysis.constrained_amount == 3 * HOUR
        assert analysis.occupying_amount <= analysis.availability_amount
        assert analysis.planned_amount <= analysis.availability_amount
        assert analysis.usable_amount <= analysis.effective_amount
