"""Tests for capacity analysis (TASK-045).

Pins pipeline step 5 — "Analyze time environment" (docs/04) — the
deterministic composition of the capacity chain: availability windows
→ hard constraints → occupying commitments → planned → effective
(history-adjusted) → usable (buffered).
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.availability import create_availability_window
from backcasting.domain.buffer import create_buffer
from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.calendar_event import create_event
from backcasting.domain.capacity_analysis import (
    CapacityAnalysis,
    CapacityAnalysisError,
    analyze_time_environment,
)
from backcasting.domain.constraint import create_constraint_range
from backcasting.domain.effective_capacity import CapacitySample
from backcasting.domain.observed_capacity import ObservedCapacity
from backcasting.domain.planned_capacity import PlannedCapacity

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")

# 2026-06-01 is a Monday.
WEEK_START = datetime(2026, 6, 1, tzinfo=UTC)
WEEK_END = WEEK_START + timedelta(days=7)
PREV_WEEK_END = WEEK_START
PREV_WEEK_START = WEEK_START - timedelta(days=7)
HOUR = timedelta(hours=1)


@pytest.fixture
def calendar() -> Calendar:
    return create_calendar(uuid.uuid4(), created_at=CREATED)


@pytest.fixture
def weekday_windows(calendar: Calendar) -> tuple:
    # Monday–Friday 09:00–17:00 UTC: 40 hours over the week.
    return (
        create_availability_window(
            calendar,
            {0, 1, 2, 3, 4},
            time(9),
            time(17),
            created_at=CREATED,
        ),
    )


def _event(calendar: Calendar, day: int, start_hour: int, hours: int):
    start = WEEK_START + timedelta(days=day, hours=start_hour)
    return create_event(
        calendar, "Commitment", start, start + timedelta(hours=hours),
        created_at=CREATED,
    )


def _sample(
    calendar: Calendar, planned_hours: float, observed_hours: float
) -> CapacitySample:
    planned = PlannedCapacity(
        capacity_id=uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        period_start=PREV_WEEK_START,
        period_end=PREV_WEEK_END,
        amount=timedelta(hours=planned_hours),
        created_at=CREATED,
        updated_at=CREATED,
    )
    observed = ObservedCapacity(
        capacity_id=uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        period_start=PREV_WEEK_START,
        period_end=PREV_WEEK_END,
        amount=timedelta(hours=observed_hours),
        measured_at=PREV_WEEK_END,
    )
    return CapacitySample(planned=planned, observed=observed)


class TestFullComposition:
    def test_chain_from_windows_to_usable(self, calendar, weekday_windows) -> None:
        events = (_event(calendar, 0, 13, 2),)  # Mon 13:00–15:00, inside windows
        constraints = (
            create_constraint_range(
                calendar,
                "Focus block",
                WEEK_START + timedelta(hours=9),
                WEEK_START + timedelta(hours=12),
                created_at=CREATED,
            ),
        )
        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            events,
            constraints,
            period_start=WEEK_START,
            period_end=WEEK_END,
            created_at=CREATED,
        )
        assert analysis.availability_amount == timedelta(hours=40)
        assert analysis.commitment_amount == timedelta(hours=2)
        assert analysis.constrained_amount == timedelta(hours=3)
        assert analysis.occupying_amount == timedelta(hours=2)
        assert analysis.planned_amount == timedelta(hours=35)
        # Cold start: no history, no buffer.
        assert analysis.sample_count == 0
        assert analysis.effective_amount == timedelta(hours=35)
        assert analysis.buffer_ratio == 0.0
        assert analysis.reserved_amount == timedelta(0)
        assert analysis.usable_amount == timedelta(hours=35)

    def test_empty_environment_yields_zero(self, calendar) -> None:
        analysis = analyze_time_environment(
            calendar,
            (),
            (),
            (),
            period_start=WEEK_START,
            period_end=WEEK_END,
            created_at=CREATED,
        )
        assert analysis.availability_amount == timedelta(0)
        assert analysis.planned_amount == timedelta(0)
        assert analysis.usable_amount == timedelta(0)


class TestCommitments:
    def test_commitment_outside_windows_consumes_nothing(
        self, calendar, weekday_windows
    ) -> None:
        # Saturday 10:00–12:00: committed time, but not on availability.
        events = (_event(calendar, 5, 10, 2),)
        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            events,
            (),
            period_start=WEEK_START,
            period_end=WEEK_END,
            created_at=CREATED,
        )
        assert analysis.commitment_amount == timedelta(hours=2)
        assert analysis.occupying_amount == timedelta(0)
        assert analysis.planned_amount == timedelta(hours=40)

    def test_overlapping_commitments_count_once(
        self, calendar, weekday_windows
    ) -> None:
        events = (
            _event(calendar, 0, 10, 2),  # Mon 10:00–12:00
            _event(calendar, 0, 11, 2),  # Mon 11:00–13:00 (overlaps 1h)
        )
        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            events,
            (),
            period_start=WEEK_START,
            period_end=WEEK_END,
            created_at=CREATED,
        )
        assert analysis.commitment_amount == timedelta(hours=3)
        assert analysis.occupying_amount == timedelta(hours=3)
        assert analysis.planned_amount == timedelta(hours=37)

    def test_commitment_partially_inside_windows(
        self, calendar, weekday_windows
    ) -> None:
        # Mon 16:00–18:00: only the 16:00–17:00 hour is available.
        events = (_event(calendar, 0, 16, 2),)
        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            events,
            (),
            period_start=WEEK_START,
            period_end=WEEK_END,
            created_at=CREATED,
        )
        assert analysis.commitment_amount == timedelta(hours=2)
        assert analysis.occupying_amount == timedelta(hours=1)
        assert analysis.planned_amount == timedelta(hours=39)


class TestConstraints:
    def test_constraint_outside_availability_blocks_nothing(
        self, calendar, weekday_windows
    ) -> None:
        constraints = (
            create_constraint_range(
                calendar,
                "Night",
                WEEK_START + timedelta(hours=20),
                WEEK_START + timedelta(hours=22),
                created_at=CREATED,
            ),
        )
        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            (),
            constraints,
            period_start=WEEK_START,
            period_end=WEEK_END,
            created_at=CREATED,
        )
        assert analysis.constrained_amount == timedelta(0)
        assert analysis.planned_amount == timedelta(hours=40)

    def test_constraint_overlapping_commitment_counts_once(
        self, calendar, weekday_windows
    ) -> None:
        # The constraint blocks Mon 09:00–13:00; an event sits inside it.
        events = (_event(calendar, 0, 10, 1),)
        constraints = (
            create_constraint_range(
                calendar,
                "Blocked",
                WEEK_START + timedelta(hours=9),
                WEEK_START + timedelta(hours=13),
                created_at=CREATED,
            ),
        )
        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            events,
            constraints,
            period_start=WEEK_START,
            period_end=WEEK_END,
            created_at=CREATED,
        )
        assert analysis.constrained_amount == timedelta(hours=4)
        # The event's hour is already gone with the constraint.
        assert analysis.occupying_amount == timedelta(0)
        assert analysis.planned_amount == timedelta(hours=36)


class TestEffectiveAndBuffer:
    def test_history_adjusts_effective(self, calendar, weekday_windows) -> None:
        # Past weeks delivered half of what they planned → trust half.
        history = (_sample(calendar, 20, 10),)
        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            (),
            (),
            period_start=WEEK_START,
            period_end=WEEK_END,
            history=history,
            created_at=CREATED,
        )
        assert analysis.sample_count == 1
        assert analysis.effective_amount == timedelta(hours=20)
        assert analysis.usable_amount == timedelta(hours=20)

    def test_buffer_carves_the_reserve(self, calendar, weekday_windows) -> None:
        buffer = create_buffer(
            calendar,
            0.25,
            period_start=WEEK_START,
            period_end=WEEK_END,
            created_at=CREATED,
        )
        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            (),
            (),
            period_start=WEEK_START,
            period_end=WEEK_END,
            buffer=buffer,
            created_at=CREATED,
        )
        assert analysis.buffer_ratio == 0.25
        assert analysis.reserved_amount == timedelta(hours=10)
        assert analysis.usable_amount == timedelta(hours=30)

    def test_history_and_buffer_compose(self, calendar, weekday_windows) -> None:
        buffer = create_buffer(
            calendar,
            0.2,
            period_start=WEEK_START,
            period_end=WEEK_END,
        )
        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            (),
            (),
            period_start=WEEK_START,
            period_end=WEEK_END,
            history=(_sample(calendar, 20, 10),),
            buffer=buffer,
            created_at=CREATED,
        )
        assert analysis.effective_amount == timedelta(hours=20)
        assert analysis.reserved_amount == timedelta(hours=4)
        assert analysis.usable_amount == timedelta(hours=16)

    def test_buffer_of_other_calendar_is_rejected(
        self, calendar, weekday_windows
    ) -> None:
        other = create_calendar(uuid.uuid4(), created_at=CREATED)
        buffer = create_buffer(
            other, 0.25, period_start=WEEK_START, period_end=WEEK_END
        )
        with pytest.raises(CapacityAnalysisError, match="does not belong"):
            analyze_time_environment(
                calendar,
                weekday_windows,
                (),
                (),
                period_start=WEEK_START,
                period_end=WEEK_END,
                buffer=buffer,
            )

    def test_buffer_of_other_period_is_rejected(
        self, calendar, weekday_windows
    ) -> None:
        buffer = create_buffer(
            calendar,
            0.25,
            period_start=PREV_WEEK_START,
            period_end=PREV_WEEK_END,
        )
        with pytest.raises(Exception, match="same period"):
            analyze_time_environment(
                calendar,
                weekday_windows,
                (),
                (),
                period_start=WEEK_START,
                period_end=WEEK_END,
                buffer=buffer,
            )


class TestOwnershipAndValidation:
    def test_foreign_window_is_rejected(self, calendar) -> None:
        other = create_calendar(uuid.uuid4(), created_at=CREATED)
        foreign_window = create_availability_window(
            other, {0}, time(9), time(17), created_at=CREATED
        )
        with pytest.raises(CapacityAnalysisError, match="does not belong"):
            analyze_time_environment(
                calendar,
                (foreign_window,),
                (),
                (),
                period_start=WEEK_START,
                period_end=WEEK_END,
            )

    def test_foreign_event_is_rejected(self, calendar, weekday_windows) -> None:
        other = create_calendar(uuid.uuid4(), created_at=CREATED)
        foreign_event = create_event(
            other, "X", WEEK_START + timedelta(hours=9),
            WEEK_START + timedelta(hours=10), created_at=CREATED,
        )
        with pytest.raises(CapacityAnalysisError, match="does not belong"):
            analyze_time_environment(
                calendar,
                weekday_windows,
                (foreign_event,),
                (),
                period_start=WEEK_START,
                period_end=WEEK_END,
            )

    def test_foreign_constraint_is_rejected(self, calendar, weekday_windows) -> None:
        other = create_calendar(uuid.uuid4(), created_at=CREATED)
        foreign_constraint = create_constraint_range(
            other, "X", WEEK_START, WEEK_START + HOUR, created_at=CREATED
        )
        with pytest.raises(CapacityAnalysisError, match="does not belong"):
            analyze_time_environment(
                calendar,
                weekday_windows,
                (),
                (foreign_constraint,),
                period_start=WEEK_START,
                period_end=WEEK_END,
            )

    def test_non_tuple_inputs_are_rejected(self, calendar, weekday_windows) -> None:
        with pytest.raises(CapacityAnalysisError, match="windows must be"):
            analyze_time_environment(
                calendar,
                [weekday_windows[0]],  # type: ignore[arg-type]
                (),
                (),
                period_start=WEEK_START,
                period_end=WEEK_END,
            )

    def test_inverted_period_is_rejected(self, calendar, weekday_windows) -> None:
        with pytest.raises(CapacityAnalysisError, match="period_end must be after"):
            analyze_time_environment(
                calendar,
                weekday_windows,
                (),
                (),
                period_start=WEEK_END,
                period_end=WEEK_START,
            )

    def test_naive_period_is_rejected(self, calendar, weekday_windows) -> None:
        with pytest.raises(CapacityAnalysisError, match="timezone-aware"):
            analyze_time_environment(
                calendar,
                weekday_windows,
                (),
                (),
                period_start=WEEK_START.replace(tzinfo=None),
                period_end=WEEK_END,
            )

    def test_rejects_non_calendar(self) -> None:
        with pytest.raises(TypeError, match="calendar must be a Calendar"):
            analyze_time_environment(
                "calendar",  # type: ignore[arg-type]
                (),
                (),
                (),
                period_start=WEEK_START,
                period_end=WEEK_END,
            )


class TestRecordInvariants:
    def _analysis(self, calendar: Calendar, **overrides) -> CapacityAnalysis:
        fields = dict(
            analysis_id=uuid.uuid4(),
            calendar_id=calendar.calendar_id,
            period_start=WEEK_START,
            period_end=WEEK_END,
            availability_amount=timedelta(hours=40),
            commitment_amount=timedelta(0),
            constrained_amount=timedelta(0),
            occupying_amount=timedelta(0),
            planned_amount=timedelta(hours=40),
            effective_amount=timedelta(hours=40),
            sample_count=0,
            buffer_ratio=0.0,
            reserved_amount=timedelta(0),
            usable_amount=timedelta(hours=40),
            created_at=CREATED,
            updated_at=CREATED,
        )
        fields.update(overrides)
        return CapacityAnalysis(**fields)

    def test_negative_amount_is_rejected(self, calendar) -> None:
        with pytest.raises(CapacityAnalysisError, match="non-negative timedelta"):
            self._analysis(calendar, planned_amount=-HOUR)

    def test_amounts_capped_by_availability(self, calendar) -> None:
        with pytest.raises(CapacityAnalysisError, match="not exceed availability"):
            self._analysis(calendar, constrained_amount=timedelta(hours=41))

    def test_usable_capped_by_effective(self, calendar) -> None:
        with pytest.raises(CapacityAnalysisError, match="not exceed effective"):
            self._analysis(
                calendar,
                usable_amount=timedelta(hours=41),
            )

    def test_ratio_bounds(self, calendar) -> None:
        with pytest.raises(CapacityAnalysisError, match="buffer_ratio"):
            self._analysis(calendar, buffer_ratio=1.0)

    def test_non_uuid_ids_are_rejected(self, calendar) -> None:
        with pytest.raises(CapacityAnalysisError, match="analysis_id must be a UUID"):
            self._analysis(calendar, analysis_id="id")

    def test_stamps_must_be_utc_and_ordered(self, calendar) -> None:
        with pytest.raises(CapacityAnalysisError, match="must not precede"):
            self._analysis(
                calendar,
                updated_at=CREATED - timedelta(seconds=1),
            )


class TestFactories:
    def test_injectable_id_and_clock(self, calendar, weekday_windows) -> None:
        analysis_id = uuid.uuid4()
        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            (),
            (),
            period_start=WEEK_START,
            period_end=WEEK_END,
            analysis_id=analysis_id,
            created_at=CREATED,
        )
        assert analysis.analysis_id == analysis_id
        assert analysis.created_at == CREATED
        assert analysis.updated_at == CREATED

    def test_usable_feeds_the_feasibility_rule(
        self, calendar, weekday_windows
    ) -> None:
        # The analysis's usable_amount is exactly the input
        # execute_backcasting expects as usable_capacity.
        from backcasting.domain.feasibility import evaluate_feasibility

        analysis = analyze_time_environment(
            calendar,
            weekday_windows,
            (_event(calendar, 0, 13, 2),),
            (),
            period_start=WEEK_START,
            period_end=WEEK_END,
            buffer=create_buffer(
                calendar, 0.25, period_start=WEEK_START, period_end=WEEK_END
            ),
            created_at=CREATED,
        )
        result = evaluate_feasibility(
            timedelta(hours=19),  # required workload
            analysis.reserved_amount,
            analysis.usable_amount,
        )
        assert result.feasible  # 19 + 9.5 ≤ 28.5 — exactly at the boundary
