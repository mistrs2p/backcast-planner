"""Tests for capacity filtering of slots (TASK-059).

Pins the capacity layer of the scheduling hierarchy (docs/05): the
goal's remaining budget gates the task (NO_CAPACITY when it cannot
hold the duration), and slots are clipped to the analyzed-capacity
period — time outside it is backed by no analysis.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.calendar import create_calendar
from backcasting.domain.capacity_filter import (
    CapacityFilterError,
    filter_slots_by_capacity,
)
from backcasting.domain.candidate_slot import CandidateSlot

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)

MON = CandidateSlot(start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=17))
TUE = CandidateSlot(
    start=(MONDAY + timedelta(days=1)).replace(hour=9),
    end=(MONDAY + timedelta(days=1)).replace(hour=17),
)


class TestBudgetGate:
    def test_budget_below_duration_yields_nothing(self) -> None:
        result = filter_slots_by_capacity(
            (MON,),
            period_start=MONDAY,
            period_end=MONDAY + timedelta(days=5),
            budget=2 * HOUR,
            duration=3 * HOUR,
        )
        assert result == ()

    def test_budget_equal_to_duration_passes(self) -> None:
        result = filter_slots_by_capacity(
            (MON,),
            period_start=MONDAY,
            period_end=MONDAY + timedelta(days=5),
            budget=3 * HOUR,
            duration=3 * HOUR,
        )
        assert result == (MON,)

    def test_generous_budget_keeps_all_slots(self) -> None:
        result = filter_slots_by_capacity(
            (MON, TUE),
            period_start=MONDAY,
            period_end=MONDAY + timedelta(days=5),
            budget=40 * HOUR,
            duration=HOUR,
        )
        assert result == (MON, TUE)

    def test_zero_budget_rejects_any_task(self) -> None:
        result = filter_slots_by_capacity(
            (MON,),
            period_start=MONDAY,
            period_end=MONDAY + timedelta(days=5),
            budget=timedelta(0),
            duration=HOUR,
        )
        assert result == ()


class TestPeriodWindow:
    def test_slots_are_clipped_to_the_period(self) -> None:
        result = filter_slots_by_capacity(
            (MON,),
            period_start=MONDAY.replace(hour=11),
            period_end=MONDAY.replace(hour=15),
            budget=HOUR,
            duration=HOUR,
        )
        assert result == (
            CandidateSlot(
                start=MONDAY.replace(hour=11), end=MONDAY.replace(hour=15)
            ),
        )

    def test_slot_entirely_outside_the_period_disappears(self) -> None:
        result = filter_slots_by_capacity(
            (MON,),
            period_start=MONDAY.replace(hour=18),
            period_end=MONDAY.replace(hour=20),
            budget=HOUR,
            duration=HOUR,
        )
        assert result == ()

    def test_clipped_piece_shorter_than_duration_disappears(self) -> None:
        # Slot 09–17 clipped to 09–10:30 → 1.5h piece.
        result = filter_slots_by_capacity(
            (MON,),
            period_start=MONDAY,
            period_end=MONDAY.replace(hour=10, minute=30),
            budget=2 * HOUR,
            duration=2 * HOUR,
        )
        assert result == ()

    def test_period_boundaries_are_half_open(self) -> None:
        """A period starting exactly at the slot's end removes it."""
        result = filter_slots_by_capacity(
            (MON,),
            period_start=MONDAY.replace(hour=17),
            period_end=MONDAY.replace(hour=20),
            budget=HOUR,
            duration=HOUR,
        )
        assert result == ()

    def test_result_preserves_input_order(self) -> None:
        # Generation returns slots chronologically; the filter keeps
        # that order rather than re-sorting.
        result = filter_slots_by_capacity(
            (MON, TUE),
            period_start=MONDAY,
            period_end=MONDAY + timedelta(days=5),
            budget=HOUR,
            duration=HOUR,
        )
        assert result == (MON, TUE)


class TestWiring:
    def test_pool_share_gates_the_task(self) -> None:
        from backcasting.domain.capacity_pool import (
            CapacityAllocation,
            allocate_capacity,
        )
        from backcasting.domain.effective_capacity import EffectiveCapacity

        goal_id = uuid.uuid4()
        effective = EffectiveCapacity(
            capacity_id=uuid.uuid4(),
            calendar_id=uuid.uuid4(),
            period_start=MONDAY,
            period_end=MONDAY + timedelta(days=7),
            amount=10 * HOUR,
            planned_amount=10 * HOUR,
            observed_amount=timedelta(0),
            sample_count=0,
        )
        pool = allocate_capacity(
            effective,
            (CapacityAllocation(goal_id=goal_id, amount=2 * HOUR),),
        )
        result = filter_slots_by_capacity(
            (MON,),
            period_start=pool.period_start,
            period_end=pool.period_end,
            budget=pool.allocation_for(goal_id),
            duration=3 * HOUR,
        )
        assert result == ()
        result = filter_slots_by_capacity(
            (MON,),
            period_start=pool.period_start,
            period_end=pool.period_end,
            budget=pool.allocation_for(goal_id),
            duration=2 * HOUR,
        )
        assert result == (MON,)

    def test_constraint_filter_composes_before_capacity(self) -> None:
        from backcasting.domain.constraint_filter import filter_slots_by_constraints
        from backcasting.domain.constraint import (
            create_constraint_range,
        )

        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        lunch = create_constraint_range(
            calendar,
            "lunch",
            MONDAY.replace(hour=12),
            MONDAY.replace(hour=13),
            created_at=CREATED,
        )
        constrained = filter_slots_by_constraints(
            (MON,), (lunch,), duration=HOUR
        )
        result = filter_slots_by_capacity(
            constrained,
            period_start=MONDAY,
            period_end=MONDAY + timedelta(days=1),
            budget=5 * HOUR,
            duration=HOUR,
        )
        assert len(result) == 2
        assert result[0].end == MONDAY.replace(hour=12)
        assert result[1].start == MONDAY.replace(hour=13)


class TestValidation:
    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(CapacityFilterError, match="slots must be a tuple"):
            filter_slots_by_capacity(
                [MON],  # type: ignore[arg-type]
                period_start=MONDAY,
                period_end=MONDAY + timedelta(days=1),
                budget=HOUR,
                duration=HOUR,
            )
        with pytest.raises(CapacityFilterError, match="period_end must be after"):
            filter_slots_by_capacity(
                (MON,),
                period_start=MONDAY + timedelta(days=1),
                period_end=MONDAY,
                budget=HOUR,
                duration=HOUR,
            )
        with pytest.raises(CapacityFilterError, match="budget must be"):
            filter_slots_by_capacity(
                (MON,),
                period_start=MONDAY,
                period_end=MONDAY + timedelta(days=1),
                budget=-HOUR,
                duration=HOUR,
            )
        with pytest.raises(CapacityFilterError, match="strictly positive"):
            filter_slots_by_capacity(
                (MON,),
                period_start=MONDAY,
                period_end=MONDAY + timedelta(days=1),
                budget=HOUR,
                duration=timedelta(0),
            )
        with pytest.raises(CapacityFilterError, match="period_start"):
            filter_slots_by_capacity(
                (MON,),
                period_start=datetime(2026, 6, 1),
                period_end=MONDAY + timedelta(days=1),
                budget=HOUR,
                duration=HOUR,
            )
