"""Tests for preference scoring of slots (TASK-062).

Pins the soft layer of the hierarchy (docs/05): preferences never
reject a candidate — they score and rank it. Direction, weight, and
overlap combine deterministically; ties keep input (chronological)
order; with no preferences the layer abstains entirely.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.calendar import create_calendar
from backcasting.domain.preference import (
    PreferenceDirection,
    create_preference,
)
from backcasting.domain.preference_scoring import (
    PreferenceScoringError,
    rank_slots_by_preferences,
    score_slot,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)


@pytest.fixture
def calendar():
    return create_calendar(uuid.uuid4(), created_at=CREATED)


def _slot(day_offset=0, start_hour=9, end_hour=17):
    day = MONDAY + timedelta(days=day_offset)
    return CandidateSlot(
        start=day.replace(hour=start_hour), end=day.replace(hour=end_hour)
    )


def _prefer(calendar, start_hour, end_hour, weight=3, weekdays=(0,)):
    return create_preference(
        calendar,
        PreferenceDirection.PREFER,
        frozenset(weekdays),
        time(start_hour),
        time(end_hour),
        weight=weight,
        created_at=CREATED,
    )


def _avoid(calendar, start_hour, end_hour, weight=3, weekdays=(0,)):
    return create_preference(
        calendar,
        PreferenceDirection.AVOID,
        frozenset(weekdays),
        time(start_hour),
        time(end_hour),
        weight=weight,
        created_at=CREATED,
    )


class TestScoreSlot:
    def test_no_preferences_scores_zero(self) -> None:
        assert score_slot(_slot(), ()) == 0.0

    def test_full_containment_scores_the_weight(self, calendar) -> None:
        prefer = _prefer(calendar, 9, 17, weight=4)
        assert score_slot(_slot(), (prefer,)) == 4.0

    def test_overlap_scales_linearly(self, calendar) -> None:
        prefer = _prefer(calendar, 9, 13, weight=4)  # 4h of the 8h slot
        assert score_slot(_slot(), (prefer,)) == pytest.approx(2.0)

    def test_touching_window_scores_zero(self, calendar) -> None:
        """Half-open: ending exactly as a window begins does not apply."""
        prefer = _prefer(calendar, 17, 20)
        assert score_slot(_slot(), (prefer,)) == 0.0

    def test_avoid_contributes_negatively(self, calendar) -> None:
        avoid = _avoid(calendar, 9, 17, weight=2)
        assert score_slot(_slot(), (avoid,)) == -2.0

    def test_weight_scales_the_contribution(self, calendar) -> None:
        light = _prefer(calendar, 9, 17, weight=1)
        heavy = _prefer(calendar, 9, 17, weight=5)
        assert score_slot(_slot(), (light,)) == 1.0
        assert score_slot(_slot(), (heavy,)) == 5.0

    def test_equal_prefer_and_avoid_cancel(self, calendar) -> None:
        prefer = _prefer(calendar, 9, 17, weight=5)
        avoid = _avoid(calendar, 9, 17, weight=5)
        assert score_slot(_slot(), (prefer, avoid)) == 0.0

    def test_multiple_preferences_sum(self, calendar) -> None:
        morning = _prefer(calendar, 9, 13, weight=2)  # +1.0 on 8h
        evening = _avoid(calendar, 15, 17, weight=2)  # −0.5 on 8h
        assert score_slot(_slot(), (morning, evening)) == pytest.approx(0.5)

    def test_non_matching_weekday_scores_zero(self, calendar) -> None:
        sunday = _prefer(calendar, 9, 17, weekdays=(6,))
        assert score_slot(_slot(), (sunday,)) == 0.0

    def test_multi_day_slot_overlaps_each_day_once(self, calendar) -> None:
        """A slot spanning days sums the windows it touches."""
        daily = _prefer(calendar, 9, 12, weight=2, weekdays=(0, 1))
        slot = CandidateSlot(
            start=MONDAY.replace(hour=9), end=(MONDAY + timedelta(days=1)).replace(hour=17)
        )
        # 3h inside Monday + 3h inside Tuesday = 6h of a 32h slot.
        assert score_slot(slot, (daily,)) == pytest.approx(2 * (6 * HOUR / slot.duration))

    def test_rejects_bad_arguments(self, calendar) -> None:
        with pytest.raises(PreferenceScoringError, match="slot must be a CandidateSlot"):
            score_slot("slot", ())  # type: ignore[arg-type]
        with pytest.raises(PreferenceScoringError, match="preferences must be a tuple"):
            score_slot(_slot(), [_prefer(calendar, 9, 17)])  # type: ignore[arg-type]
        with pytest.raises(PreferenceScoringError, match="Preference instances"):
            score_slot(_slot(), ("prefer",))  # type: ignore[arg-type]


class TestRankSlotsByPreferences:
    def test_no_preferences_keeps_input_order(self) -> None:
        slots = (_slot(day_offset=0), _slot(day_offset=1))
        assert rank_slots_by_preferences(slots, ()) == slots

    def test_preferred_slot_ranks_first(self, calendar) -> None:
        morning = _prefer(calendar, 9, 12)
        early, late = _slot(start_hour=9), _slot(start_hour=13)
        assert rank_slots_by_preferences((late, early), (morning,)) == (early, late)

    def test_avoided_slot_ranks_last(self, calendar) -> None:
        afternoon = _avoid(calendar, 13, 17)
        early, late = _slot(start_hour=9), _slot(start_hour=13)
        assert rank_slots_by_preferences((late, early), (afternoon,)) == (early, late)

    def test_ranking_never_drops_a_slot(self, calendar) -> None:
        """The soft layer guides, it never rejects (docs/05)."""
        all_day = _avoid(calendar, 0, 23, weight=5, weekdays=tuple(range(7)))
        slots = (_slot(day_offset=0), _slot(day_offset=1))
        ranked = rank_slots_by_preferences(slots, (all_day,))
        assert sorted(ranked, key=lambda s: s.start) == sorted(slots, key=lambda s: s.start)

    def test_equal_scores_keep_input_order(self, calendar) -> None:
        """Generation order (chronological) remains the tie-breaker."""
        morning = _prefer(calendar, 9, 12)
        slots = (_slot(day_offset=0), _slot(day_offset=1), _slot(day_offset=2))
        assert rank_slots_by_preferences(slots, (morning,)) == slots

    def test_rejects_bad_arguments(self, calendar) -> None:
        with pytest.raises(PreferenceScoringError, match="slots must be a tuple"):
            rank_slots_by_preferences([_slot()], ())  # type: ignore[arg-type]
        with pytest.raises(PreferenceScoringError, match="CandidateSlot instances"):
            rank_slots_by_preferences((_slot(), "x"), ())  # type: ignore[arg-type]


class TestWiring:
    def test_scoring_composes_after_the_deadline_layer(self, calendar) -> None:
        """What survives the subtractive layers is what gets ranked."""
        from backcasting.domain.deadline_filter import filter_slots_by_deadline
        from backcasting.domain.goal import create_goal
        from backcasting.domain.plan import create_plan
        from backcasting.domain.task import create_task

        goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
        plan = create_plan(goal, 20 * HOUR, created_at=CREATED)
        task = create_task(
            plan, "Task", deadline=(MONDAY + timedelta(days=1)).replace(hour=12),
            created_at=CREATED,
        )
        slots = (_slot(day_offset=0), _slot(day_offset=1), _slot(day_offset=2))
        clipped = filter_slots_by_deadline(slots, task=task, duration=HOUR)

        morning = _prefer(calendar, 9, 12, weight=5, weekdays=(0, 1))
        ranked = rank_slots_by_preferences(clipped, (morning,))
        # Tuesday is clipped to 09:00–12:00 — fully inside the window,
        # so it outranks the full Monday slot.
        assert ranked[0] == CandidateSlot(
            start=(MONDAY + timedelta(days=1)).replace(hour=9),
            end=(MONDAY + timedelta(days=1)).replace(hour=12),
        )
        assert len(ranked) == 2

    def test_dst_preserves_wall_clock_scoring(self, calendar) -> None:
        """London spring-forward: the 09:00–17:00 preference still
        matches the wall-clock window, not the shifted UTC span."""
        tz = ZoneInfo("Europe/London")
        # Sunday 2026-03-29 in London: 09:00 local = 08:00 UTC (after
        # the 01:00 jump); the window is 8 wall-clock hours.
        sunday = datetime(2026, 3, 29, tzinfo=timezone.utc)
        slot = CandidateSlot(
            start=sunday.replace(hour=8), end=sunday.replace(hour=16)
        )
        prefer = create_preference(
            calendar,
            PreferenceDirection.PREFER,
            frozenset({6}),  # Sunday
            time(9),
            time(17),
            timezone=tz,
            weight=5,
            created_at=CREATED,
        )
        assert score_slot(slot, (prefer,)) == pytest.approx(5.0)
