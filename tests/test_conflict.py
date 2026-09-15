"""Tests for calendar conflict detection (TASK-036)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.calendar_event import create_event
from backcasting.domain.conflict import Conflict, ConflictError, detect_conflicts

UTC = timezone.utc


@pytest.fixture
def calendar() -> Calendar:
    return create_calendar(uuid.UUID(int=1))


def _event(calendar, start: datetime, hours: float, *, title="Block"):
    return create_event(
        calendar,
        title,
        start,
        start + timedelta(hours=hours),
    )


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


class TestArgumentValidation:
    def test_rejects_non_calendar(self):
        with pytest.raises(TypeError, match="calendar must be a Calendar"):
            detect_conflicts("calendar", ())

    def test_rejects_non_tuple_events(self, calendar):
        with pytest.raises(ConflictError, match="events must be a tuple"):
            detect_conflicts(calendar, [])

    def test_rejects_non_event_members(self, calendar):
        with pytest.raises(ConflictError, match="CalendarEvent instances"):
            detect_conflicts(calendar, ("event",))

    def test_rejects_event_from_other_calendar(self, calendar):
        other = create_calendar(uuid.UUID(int=2))
        event = create_event(other, "Elsewhere", _at(1, 9), _at(1, 10))
        with pytest.raises(ConflictError, match="does not belong to this calendar"):
            detect_conflicts(calendar, (event,))

    def test_accepts_empty_tuple(self, calendar):
        assert detect_conflicts(calendar, ()) == ()


class TestNoConflict:
    def test_single_event_never_conflicts(self, calendar):
        events = (_event(calendar, _at(1, 9), 1),)
        assert detect_conflicts(calendar, events) == ()

    def test_disjoint_events_do_not_conflict(self, calendar):
        events = (
            _event(calendar, _at(1, 9), 1),
            _event(calendar, _at(1, 11), 1),
            _event(calendar, _at(2, 9), 1),
        )
        assert detect_conflicts(calendar, events) == ()

    def test_touching_events_do_not_conflict(self, calendar):
        events = (
            _event(calendar, _at(1, 9), 1),
            _event(calendar, _at(1, 10), 1),
        )
        assert detect_conflicts(calendar, events) == ()

    def test_touching_is_not_a_conflict_in_either_order(self, calendar):
        late = _event(calendar, _at(1, 10), 1)
        early = _event(calendar, _at(1, 9), 1)
        assert detect_conflicts(calendar, (late, early)) == ()


class TestOverlapDetection:
    def test_partial_overlap_produces_one_conflict(self, calendar):
        first = _event(calendar, _at(1, 9), 2)
        second = _event(calendar, _at(1, 10), 2)
        (conflict,) = detect_conflicts(calendar, (second, first))
        assert conflict.first is first
        assert conflict.second is second
        assert conflict.start == _at(1, 10)
        assert conflict.end == _at(1, 11)

    def test_identical_intervals_conflict_over_the_whole_interval(self, calendar):
        first = _event(calendar, _at(1, 9), 1)
        second = _event(calendar, _at(1, 9), 1, title="Clash")
        (conflict,) = detect_conflicts(calendar, (first, second))
        assert conflict.start == _at(1, 9)
        assert conflict.end == _at(1, 10)
        assert conflict.end - conflict.start == timedelta(hours=1)

    def test_contained_event_conflicts_over_contained_interval(self, calendar):
        outer = _event(calendar, _at(1, 9), 4)
        inner = _event(calendar, _at(1, 10), 1)
        (conflict,) = detect_conflicts(calendar, (outer, inner))
        assert conflict.first is outer
        assert conflict.second is inner
        assert conflict.start == _at(1, 10)
        assert conflict.end == _at(1, 11)

    def test_ordering_tie_breaks_by_end_then_event_id(self, calendar):
        shared_start = _at(1, 9)
        shorter_id = uuid.UUID(int=10)
        longer_id = uuid.UUID(int=20)
        short = create_event(
            calendar, "Short", shared_start, shared_start + timedelta(hours=1),
            event_id=shorter_id,
        )
        long = create_event(
            calendar, "Long", shared_start, shared_start + timedelta(hours=2),
            event_id=longer_id,
        )
        (conflict,) = detect_conflicts(calendar, (long, short))
        assert conflict.first is short
        assert conflict.second is long
        assert conflict.start == shared_start
        assert conflict.end == shared_start + timedelta(hours=1)

    def test_three_mutually_overlapping_events_yield_three_conflicts(self, calendar):
        events = (
            _event(calendar, _at(1, 9), 3),
            _event(calendar, _at(1, 10), 3),
            _event(calendar, _at(1, 11), 3),
        )
        conflicts = detect_conflicts(calendar, events)
        assert len(conflicts) == 3
        assert {(c.first.title, c.second.title) for c in conflicts} == {
            ("Block", "Block"),
        }
        # pairs: (0,1), (0,2), (1,2) in sweep order
        assert conflicts[0].start == _at(1, 10)
        assert conflicts[1].start == _at(1, 11)
        assert conflicts[2].start == _at(1, 11)

    def test_chain_overlaps_without_first_last_clash(self, calendar):
        events = (
            _event(calendar, _at(1, 9), 2),   # 09–11
            _event(calendar, _at(1, 10), 2),  # 10–12
            _event(calendar, _at(1, 11), 2),  # 11–13
        )
        conflicts = detect_conflicts(calendar, events)
        assert len(conflicts) == 2
        assert conflicts[0].start == _at(1, 10)
        assert conflicts[0].end == _at(1, 11)
        assert conflicts[1].start == _at(1, 11)
        assert conflicts[1].end == _at(1, 12)

    def test_conflict_across_days(self, calendar):
        first = _event(calendar, _at(1, 23), 2)   # 23:00–01:00 next day
        second = _event(calendar, _at(2, 0), 1)   # 00:00–01:00
        (conflict,) = detect_conflicts(calendar, (first, second))
        assert conflict.start == _at(2, 0)
        assert conflict.end == _at(2, 1)


class TestDeterminism:
    def test_input_order_does_not_change_output(self, calendar):
        a = _event(calendar, _at(1, 9), 3)
        b = _event(calendar, _at(1, 10), 3)
        c = _event(calendar, _at(1, 11), 3)
        forward = detect_conflicts(calendar, (a, b, c))
        backward = detect_conflicts(calendar, (c, b, a))
        shuffled = detect_conflicts(calendar, (b, c, a))
        assert forward == backward == shuffled
        assert len(forward) == 3

    def test_each_pair_reported_exactly_once(self, calendar):
        first = _event(calendar, _at(1, 9), 2)
        second = _event(calendar, _at(1, 10), 2)
        conflicts = detect_conflicts(calendar, (first, second, first))
        # the duplicated event clashes with both others and its twin
        assert len(conflicts) == 3


class TestConflictRecord:
    def test_conflict_is_frozen(self, calendar):
        first = _event(calendar, _at(1, 9), 2)
        second = _event(calendar, _at(1, 10), 2)
        (conflict,) = detect_conflicts(calendar, (first, second))
        assert isinstance(conflict, Conflict)
        with pytest.raises(AttributeError):
            conflict.start = _at(1, 10)

    def test_conflict_carries_both_events(self, calendar):
        first = _event(calendar, _at(1, 9), 2, title="Standup")
        second = _event(calendar, _at(1, 10), 2, title="Review")
        (conflict,) = detect_conflicts(calendar, (first, second))
        assert conflict.first.title == "Standup"
        assert conflict.second.title == "Review"
        assert conflict.first.calendar_id == calendar.calendar_id
        assert conflict.second.calendar_id == calendar.calendar_id
