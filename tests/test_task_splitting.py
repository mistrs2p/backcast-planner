"""Tests for task splitting across slots (TASK-063).

Pins the placement fallback: when no single slot holds the whole
duration, the work flows greedily through the ranked slots in
granularity multiples (docs/05: 15 minutes), parts sum exactly to
the duration, and insufficient total capacity is the
NO_AVAILABLE_SLOT fact — an empty result, never a partial one.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.task_splitting import (
    DEFAULT_GRANULARITY,
    SlotAllocation,
    TaskSplittingError,
    split_task_across_slots,
)

MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
TUESDAY = MONDAY + timedelta(days=1)
HOUR = timedelta(hours=1)
QUARTER = timedelta(minutes=15)


def _slot(day_offset=0, start_hour=9, end_hour=17):
    day = MONDAY + timedelta(days=day_offset)
    return CandidateSlot(
        start=day.replace(hour=start_hour), end=day.replace(hour=end_hour)
    )


class TestSplitTaskAcrossSlots:
    def test_duration_fitting_one_slot_is_a_single_allocation(self) -> None:
        result = split_task_across_slots((_slot(),), duration=2 * HOUR)
        assert result == (
            SlotAllocation(
                slot=_slot(), start=_slot().start, end=_slot().start + 2 * HOUR
            ),
        )

    def test_remainder_flows_to_the_next_slot(self) -> None:
        """4h across a 3h slot and an 8h slot: 3h + 1h."""
        first, second = _slot(end_hour=12), _slot(day_offset=1)
        result = split_task_across_slots((first, second), duration=4 * HOUR)
        assert result == (
            SlotAllocation(slot=first, start=first.start, end=first.end),
            SlotAllocation(
                slot=second, start=second.start, end=second.start + HOUR
            ),
        )

    def test_allocation_follows_input_order_not_chronology(self) -> None:
        """Ranked order rules: a later-day slot listed first hosts first."""
        later = _slot(day_offset=2, end_hour=10)  # 1h
        earlier = _slot()  # 8h
        result = split_task_across_slots((later, earlier), duration=2 * HOUR)
        assert [a.slot for a in result] == [later, earlier]

    def test_parts_sum_exactly_to_the_duration(self) -> None:
        result = split_task_across_slots(
            (_slot(end_hour=10), _slot(day_offset=1)), duration=3 * HOUR
        )
        assert sum((a.duration for a in result), timedelta(0)) == 3 * HOUR

    def test_every_part_is_a_whole_granularity_multiple(self) -> None:
        result = split_task_across_slots(
            (_slot(end_hour=10), _slot(day_offset=1)), duration=5 * HOUR
        )
        assert [a.duration for a in result] == [HOUR, 4 * HOUR]
        for allocation in result:
            assert allocation.duration % DEFAULT_GRANULARITY == timedelta(0)

    def test_slot_shorter_than_one_granularity_is_skipped(self) -> None:
        tiny = CandidateSlot(
            start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=9, minute=10)
        )
        result = split_task_across_slots((tiny, _slot()), duration=HOUR)
        assert [a.slot for a in result] == [_slot()]

    def test_off_granularity_slot_capacity_is_floored(self) -> None:
        """A 50-minute slot hosts 45 minutes at 15-minute granularity."""
        odd = CandidateSlot(
            start=MONDAY.replace(hour=9), end=MONDAY.replace(hour=9, minute=50)
        )
        result = split_task_across_slots((odd, _slot()), duration=HOUR)
        assert result[0].duration == timedelta(minutes=45)
        assert result[1].duration == timedelta(minutes=15)

    def test_exact_boundary_consumes_the_slot_fully(self) -> None:
        slot = _slot(end_hour=10)  # exactly 1h
        result = split_task_across_slots(
            (slot, _slot(day_offset=1)), duration=3 * HOUR
        )
        assert result[0].end == slot.end
        assert result[1].duration == 2 * HOUR

    def test_allocation_never_exceeds_its_slot(self) -> None:
        result = split_task_across_slots(
            (_slot(end_hour=11), _slot(day_offset=1)), duration=5 * HOUR
        )
        for allocation in result:
            assert allocation.start >= allocation.slot.start
            assert allocation.end <= allocation.slot.end

    def test_insufficient_total_capacity_returns_empty(self) -> None:
        result = split_task_across_slots((_slot(end_hour=11),), duration=5 * HOUR)
        assert result == ()

    def test_no_slots_returns_empty(self) -> None:
        assert split_task_across_slots((), duration=HOUR) == ()

    def test_custom_granularity(self) -> None:
        slot = _slot(end_hour=11)
        result = split_task_across_slots(
            (slot,), duration=HOUR, granularity=timedelta(minutes=30)
        )
        assert result[0].duration == HOUR

    def test_off_granularity_duration_is_rejected(self) -> None:
        with pytest.raises(TaskSplittingError, match="multiple of the planning"):
            split_task_across_slots((_slot(),), duration=timedelta(minutes=50))

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(TaskSplittingError, match="slots must be a tuple"):
            split_task_across_slots([_slot()], duration=HOUR)  # type: ignore[arg-type]
        with pytest.raises(TaskSplittingError, match="CandidateSlot instances"):
            split_task_across_slots(("x",), duration=HOUR)  # type: ignore[arg-type]
        with pytest.raises(TaskSplittingError, match="strictly positive"):
            split_task_across_slots((_slot(),), duration=timedelta(0))
        with pytest.raises(TaskSplittingError, match="strictly positive"):
            split_task_across_slots(
                (_slot(),), duration=HOUR, granularity=timedelta(0)
            )


class TestWiring:
    def test_splitting_composes_after_preference_ranking(self) -> None:
        """Ranked survivors feed the splitter; the best slot hosts the most."""
        from backcasting.domain.calendar import create_calendar
        from backcasting.domain.preference import (
            PreferenceDirection,
            create_preference,
        )
        from backcasting.domain.preference_scoring import rank_slots_by_preferences

        calendar = create_calendar(uuid.uuid4())
        morning = create_preference(
            calendar,
            PreferenceDirection.PREFER,
            frozenset({0, 1}),
            time(9),
            time(12),
            weight=5,
        )
        # Monday afternoon: zero overlap, score 0. Tuesday morning:
        # 3h of a 4h slot inside the window, score 3.75 — it ranks
        # first even though Monday was generated first.
        monday = _slot(start_hour=13, end_hour=17)
        tuesday = _slot(day_offset=1, end_hour=13)
        ranked = rank_slots_by_preferences((monday, tuesday), (morning,))
        assert ranked[0] is tuesday

        result = split_task_across_slots(ranked, duration=5 * HOUR)
        assert [a.slot for a in result] == [tuesday, monday]
        assert [a.duration for a in result] == [4 * HOUR, HOUR]

    def test_split_parts_feed_dependency_gates(self) -> None:
        """A dependent's gate is the last part's end — the task truly
        finishes when its final part does."""
        slots = (_slot(end_hour=11), _slot(day_offset=1, end_hour=12))
        parts = split_task_across_slots(slots, duration=5 * HOUR)
        assert [a.duration for a in parts] == [2 * HOUR, 3 * HOUR]
        assert parts[-1].end == TUESDAY.replace(hour=12)
