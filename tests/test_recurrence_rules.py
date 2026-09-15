"""Tests for recurrence rules (TASK-031).

Pins the repeating-pattern invariants, deterministic expansion over
DAILY/WEEKLY frequencies with intervals, window and ``until`` clipping,
and the wall-clock (DST-aware) semantics mandated by docs/05.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.recurrence import (
    Frequency,
    RecurrenceError,
    RecurrenceRule,
    create_rule,
    expand_rule,
    occurrences,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc

# 2026-01-05 is a Monday.
MONDAY_9AM = datetime(2026, 1, 5, 9, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.fixture
def calendar() -> Calendar:
    return create_calendar(uuid.uuid4(), timezone=LONDON, created_at=CREATED)


def _rule(calendar: Calendar, **overrides) -> RecurrenceRule:
    kwargs: dict = {
        "title": "Morning run",
        "frequency": Frequency.WEEKLY,
        "starts_on": MONDAY_9AM,
        "duration": HOUR,
        "created_at": CREATED,
    }
    kwargs.update(overrides)
    return create_rule(calendar, **kwargs)


class TestRecurrenceRule:
    def test_valid_rule_is_accepted(self, calendar: Calendar) -> None:
        rule = _rule(calendar)
        assert rule.title == "Morning run"
        assert rule.frequency is Frequency.WEEKLY
        assert rule.interval == 1
        assert rule.by_weekday == frozenset()
        assert rule.until is None
        assert rule.timezone is LONDON
        assert rule.calendar_id == calendar.calendar_id

    def test_title_is_stripped_and_bounded(self, calendar: Calendar) -> None:
        assert _rule(calendar, title="  Run  ").title == "Run"
        with pytest.raises(RecurrenceError):
            _rule(calendar, title="x" * 201)

    @pytest.mark.parametrize("title", ["", "   "])
    def test_empty_title_is_rejected(
        self, calendar: Calendar, title: str
    ) -> None:
        with pytest.raises(RecurrenceError):
            _rule(calendar, title=title)

    def test_description_is_optional_and_bounded(self, calendar: Calendar) -> None:
        assert _rule(calendar, description="Easy pace.").description == "Easy pace."
        with pytest.raises(RecurrenceError):
            _rule(calendar, description="x" * 5001)

    def test_duration_must_be_positive_timedelta(
        self, calendar: Calendar
    ) -> None:
        with pytest.raises(RecurrenceError):
            _rule(calendar, duration=timedelta(0))
        with pytest.raises(RecurrenceError):
            _rule(calendar, duration=-HOUR)
        with pytest.raises(RecurrenceError):
            _rule(calendar, duration=60)  # type: ignore[arg-type]

    @pytest.mark.parametrize("interval", [0, -1, True, "2", 1.5])
    def test_invalid_intervals_are_rejected(
        self, calendar: Calendar, interval: object
    ) -> None:
        with pytest.raises(RecurrenceError):
            _rule(calendar, interval=interval)  # type: ignore[arg-type]

    @pytest.mark.parametrize("weekday", [7, -1, "mon", True, 3.0])
    def test_invalid_weekdays_are_rejected(
        self, calendar: Calendar, weekday: object
    ) -> None:
        with pytest.raises(RecurrenceError):
            _rule(calendar, by_weekday={weekday})  # type: ignore[arg-type]

    def test_by_weekday_rejected_for_daily(self, calendar: Calendar) -> None:
        with pytest.raises(RecurrenceError):
            _rule(calendar, frequency=Frequency.DAILY, by_weekday={0})

    def test_until_must_be_after_starts_on(self, calendar: Calendar) -> None:
        with pytest.raises(RecurrenceError):
            _rule(calendar, until=MONDAY_9AM)
        with pytest.raises(RecurrenceError):
            _rule(calendar, until=MONDAY_9AM - timedelta(seconds=1))

    def test_naive_or_non_utc_stamps_are_rejected(
        self, calendar: Calendar
    ) -> None:
        with pytest.raises(RecurrenceError):
            _rule(calendar, starts_on=datetime(2026, 1, 5, 9))
        with pytest.raises(RecurrenceError):
            _rule(
                calendar,
                starts_on=MONDAY_9AM.astimezone(ZoneInfo("Asia/Tehran")),
            )
        with pytest.raises(RecurrenceError):
            _rule(calendar, until=datetime(2026, 2, 1))
        with pytest.raises(RecurrenceError):
            _rule(calendar, created_at=datetime(2026, 1, 1))

    def test_rule_is_immutable(self, calendar: Calendar) -> None:
        rule = _rule(calendar)
        with pytest.raises(AttributeError):
            rule.interval = 2  # type: ignore[misc]


class TestOccurrencesDaily:
    def test_daily_rule_occurs_every_day(self, calendar: Calendar) -> None:
        rule = _rule(calendar, frequency=Frequency.DAILY)
        starts = occurrences(
            rule,
            window_start=datetime(2026, 1, 5, tzinfo=UTC),
            window_end=datetime(2026, 1, 8, 23, tzinfo=UTC),
        )
        assert starts == (
            datetime(2026, 1, 5, 9, tzinfo=UTC),
            datetime(2026, 1, 6, 9, tzinfo=UTC),
            datetime(2026, 1, 7, 9, tzinfo=UTC),
            datetime(2026, 1, 8, 9, tzinfo=UTC),
        )

    def test_interval_skips_days(self, calendar: Calendar) -> None:
        rule = _rule(calendar, frequency=Frequency.DAILY, interval=2)
        starts = occurrences(
            rule,
            window_start=datetime(2026, 1, 5, tzinfo=UTC),
            window_end=datetime(2026, 1, 9, 23, tzinfo=UTC),
        )
        assert starts == (
            datetime(2026, 1, 5, 9, tzinfo=UTC),
            datetime(2026, 1, 7, 9, tzinfo=UTC),
            datetime(2026, 1, 9, 9, tzinfo=UTC),
        )

    def test_window_clips_before_starts_on(self, calendar: Calendar) -> None:
        rule = _rule(calendar, frequency=Frequency.DAILY)
        starts = occurrences(
            rule,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 6, 23, tzinfo=UTC),
        )
        assert starts == (
            datetime(2026, 1, 5, 9, tzinfo=UTC),
            datetime(2026, 1, 6, 9, tzinfo=UTC),
        )

    def test_until_bounds_occurrence_starts(self, calendar: Calendar) -> None:
        rule = _rule(
            calendar,
            frequency=Frequency.DAILY,
            until=datetime(2026, 1, 6, 9, tzinfo=UTC),
        )
        starts = occurrences(
            rule,
            window_start=datetime(2026, 1, 5, tzinfo=UTC),
            window_end=datetime(2026, 1, 10, tzinfo=UTC),
        )
        assert starts == (
            datetime(2026, 1, 5, 9, tzinfo=UTC),
            datetime(2026, 1, 6, 9, tzinfo=UTC),
        )

    def test_window_before_starts_on_is_empty(
        self, calendar: Calendar
    ) -> None:
        rule = _rule(calendar, frequency=Frequency.DAILY)
        assert (
            occurrences(
                rule,
                window_start=datetime(2026, 1, 1, tzinfo=UTC),
                window_end=datetime(2026, 1, 2, tzinfo=UTC),
            )
            == ()
        )

    def test_dst_transition_preserves_local_time(self, calendar: Calendar) -> None:
        # London springs forward at 01:00 local on 2026-03-29: a 9:00
        # local occurrence is 09:00 UTC before the transition and
        # 08:00 UTC from the transition day onward.
        rule = _rule(calendar, frequency=Frequency.DAILY)
        starts = occurrences(
            rule,
            window_start=datetime(2026, 3, 28, tzinfo=UTC),
            window_end=datetime(2026, 3, 31, 23, tzinfo=UTC),
        )
        assert starts == (
            datetime(2026, 3, 28, 9, tzinfo=UTC),
            datetime(2026, 3, 29, 8, tzinfo=UTC),  # transition day
            datetime(2026, 3, 30, 8, tzinfo=UTC),
            datetime(2026, 3, 31, 8, tzinfo=UTC),
        )


class TestOccurrencesWeekly:
    def test_weekly_defaults_to_anchor_weekday(self, calendar: Calendar) -> None:
        rule = _rule(calendar)  # anchored Monday
        starts = occurrences(
            rule,
            window_start=datetime(2026, 1, 5, tzinfo=UTC),
            window_end=datetime(2026, 1, 19, 23, tzinfo=UTC),
        )
        assert starts == (
            datetime(2026, 1, 5, 9, tzinfo=UTC),
            datetime(2026, 1, 12, 9, tzinfo=UTC),
            datetime(2026, 1, 19, 9, tzinfo=UTC),
        )

    def test_multiple_weekdays_in_sorted_order(self, calendar: Calendar) -> None:
        rule = _rule(calendar, by_weekday={2, 4})  # Wednesdays and Fridays
        starts = occurrences(
            rule,
            window_start=datetime(2026, 1, 5, tzinfo=UTC),
            window_end=datetime(2026, 1, 12, 23, tzinfo=UTC),
        )
        assert starts == (
            datetime(2026, 1, 7, 9, tzinfo=UTC),  # Wednesday
            datetime(2026, 1, 9, 9, tzinfo=UTC),  # Friday
            # Monday 2026-01-12 is not in by_weekday, so no occurrence.
        )

    def test_weekly_interval_skips_weeks(self, calendar: Calendar) -> None:
        rule = _rule(calendar, interval=2)  # fortnightly Mondays
        starts = occurrences(
            rule,
            window_start=datetime(2026, 1, 5, tzinfo=UTC),
            window_end=datetime(2026, 2, 2, 23, tzinfo=UTC),
        )
        assert starts == (
            datetime(2026, 1, 5, 9, tzinfo=UTC),
            datetime(2026, 1, 19, 9, tzinfo=UTC),
            datetime(2026, 2, 2, 9, tzinfo=UTC),
        )

    def test_weekly_across_dst_boundary(self, calendar: Calendar) -> None:
        # Mondays around the 2026-03-29 spring-forward: 09:00 UTC before,
        # 08:00 UTC after — local 9:00 is preserved either way.
        rule = _rule(calendar, by_weekday={0})
        starts = occurrences(
            rule,
            window_start=datetime(2026, 3, 20, tzinfo=UTC),
            window_end=datetime(2026, 4, 6, 23, tzinfo=UTC),
        )
        assert starts == (
            datetime(2026, 3, 23, 9, tzinfo=UTC),
            datetime(2026, 3, 30, 8, tzinfo=UTC),
            datetime(2026, 4, 6, 8, tzinfo=UTC),
        )


class TestOccurrencesInputGuards:
    def test_naive_window_is_rejected(self, calendar: Calendar) -> None:
        rule = _rule(calendar, frequency=Frequency.DAILY)
        with pytest.raises(RecurrenceError):
            occurrences(
                rule,
                window_start=datetime(2026, 1, 5),
                window_end=datetime(2026, 1, 6, tzinfo=UTC),
            )

    def test_non_utc_window_is_rejected(self, calendar: Calendar) -> None:
        rule = _rule(calendar, frequency=Frequency.DAILY)
        with pytest.raises(RecurrenceError):
            occurrences(
                rule,
                window_start=datetime(2026, 1, 5, tzinfo=UTC),
                window_end=datetime(2026, 1, 6, 9, tzinfo=ZoneInfo("Asia/Tehran")),
            )

    def test_reversed_window_is_rejected(self, calendar: Calendar) -> None:
        rule = _rule(calendar, frequency=Frequency.DAILY)
        with pytest.raises(RecurrenceError):
            occurrences(
                rule,
                window_start=datetime(2026, 1, 6, tzinfo=UTC),
                window_end=datetime(2026, 1, 5, tzinfo=UTC),
            )

    def test_non_rule_is_rejected(self, calendar: Calendar) -> None:
        with pytest.raises(TypeError):
            occurrences("not a rule", window_start=MONDAY_9AM, window_end=MONDAY_9AM)


class TestExpandRule:
    def test_expands_into_events(self, calendar: Calendar) -> None:
        rule = _rule(
            calendar,
            frequency=Frequency.DAILY,
            description="Easy pace.",
            duration=2 * HOUR,
        )
        events = expand_rule(
            rule,
            calendar,
            window_start=datetime(2026, 1, 5, tzinfo=UTC),
            window_end=datetime(2026, 1, 6, 23, tzinfo=UTC),
        )
        assert len(events) == 2
        for event, day in zip(events, (5, 6)):
            assert isinstance(event, CalendarEvent)
            assert event.calendar_id == calendar.calendar_id
            assert event.title == "Morning run"
            assert event.description == "Easy pace."
            assert event.start == datetime(2026, 1, day, 9, tzinfo=UTC)
            assert event.end == datetime(2026, 1, day, 11, tzinfo=UTC)
            assert event.event_id != rule.rule_id

    def test_rejects_foreign_calendar(self, calendar: Calendar) -> None:
        rule = _rule(calendar, frequency=Frequency.DAILY)
        other = create_calendar(uuid.uuid4(), created_at=CREATED)
        with pytest.raises(RecurrenceError):
            expand_rule(
                rule,
                other,
                window_start=datetime(2026, 1, 5, tzinfo=UTC),
                window_end=datetime(2026, 1, 6, tzinfo=UTC),
            )
