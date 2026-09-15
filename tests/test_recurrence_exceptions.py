"""Tests for recurrence exceptions (TASK-032).

Pins "recurring rules may have exceptions" (docs/05): occurrences are
addressed by their original start instant, cancelled occurrences are
dropped, rescheduled ones move (optionally re-durationed), and
conflicting or foreign exceptions are rejected.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.recurrence import Frequency, RecurrenceRule, create_rule
from backcasting.domain.recurrence_exception import (
    ExceptionKind,
    RecurrenceException,
    RecurrenceExceptionError,
    cancel_occurrence,
    expand_with_exceptions,
    reschedule_occurrence,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
HOUR = timedelta(hours=1)

MONDAY_9AM = datetime(2026, 1, 5, 9, tzinfo=UTC)
TUESDAY_9AM = datetime(2026, 1, 6, 9, tzinfo=UTC)
WEDNESDAY_9AM = datetime(2026, 1, 7, 9, tzinfo=UTC)
TUESDAY_11AM = datetime(2026, 1, 6, 11, tzinfo=UTC)


@pytest.fixture
def calendar() -> Calendar:
    return create_calendar(uuid.uuid4(), timezone=LONDON, created_at=CREATED)


@pytest.fixture
def rule(calendar: Calendar) -> RecurrenceRule:
    return create_rule(
        calendar,
        "Morning run",
        Frequency.DAILY,
        MONDAY_9AM,
        HOUR,
        created_at=CREATED,
    )


def _expand(
    rule: RecurrenceRule,
    calendar: Calendar,
    exceptions=(),
    window_start=datetime(2026, 1, 5, tzinfo=UTC),
    window_end=datetime(2026, 1, 7, 23, tzinfo=UTC),
):
    return expand_with_exceptions(
        rule,
        calendar,
        exceptions,
        window_start=window_start,
        window_end=window_end,
    )


class TestRecurrenceException:
    def _valid_kwargs(self) -> dict:
        return {
            "exception_id": uuid.uuid4(),
            "rule_id": uuid.uuid4(),
            "kind": ExceptionKind.CANCELLED,
            "original_start": TUESDAY_9AM,
            "created_at": CREATED,
            "updated_at": CREATED,
        }

    def test_kinds_match_semantics(self) -> None:
        assert [k.value for k in ExceptionKind] == ["cancelled", "rescheduled"]

    def test_valid_cancellation_is_accepted(self) -> None:
        exception = RecurrenceException(**self._valid_kwargs())
        assert exception.kind is ExceptionKind.CANCELLED
        assert exception.new_start is None
        assert exception.new_duration is None

    def test_valid_reschedule_is_accepted(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs.update(
            kind=ExceptionKind.RESCHEDULED,
            new_start=TUESDAY_11AM,
            new_duration=2 * HOUR,
        )
        exception = RecurrenceException(**kwargs)
        assert exception.new_start == TUESDAY_11AM
        assert exception.new_duration == 2 * HOUR

    def test_cancelled_with_replacement_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["new_start"] = TUESDAY_11AM
        with pytest.raises(RecurrenceExceptionError):
            RecurrenceException(**kwargs)

    def test_rescheduled_without_new_start_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["kind"] = ExceptionKind.RESCHEDULED
        with pytest.raises(RecurrenceExceptionError):
            RecurrenceException(**kwargs)

    def test_rescheduled_to_same_instant_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs.update(kind=ExceptionKind.RESCHEDULED, new_start=TUESDAY_9AM)
        with pytest.raises(RecurrenceExceptionError):
            RecurrenceException(**kwargs)

    @pytest.mark.parametrize(
        "new_duration", [timedelta(0), -HOUR, 60, None]
    )
    def test_invalid_new_durations_are_rejected(
        self, new_duration: object
    ) -> None:
        kwargs = self._valid_kwargs()
        kwargs.update(
            kind=ExceptionKind.RESCHEDULED,
            new_start=TUESDAY_11AM,
            new_duration=new_duration,
        )
        if new_duration is None:
            # None simply means "keep the rule's duration" — allowed.
            RecurrenceException(**kwargs)
        else:
            with pytest.raises(RecurrenceExceptionError):
                RecurrenceException(**kwargs)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("original_start", datetime(2026, 1, 6, 9)),
            ("original_start", TUESDAY_9AM.astimezone(ZoneInfo("Asia/Tehran"))),
            ("created_at", datetime(2026, 1, 1)),
        ],
    )
    def test_naive_or_non_utc_stamps_are_rejected(
        self, field: str, value: object
    ) -> None:
        kwargs = self._valid_kwargs()
        kwargs[field] = value
        with pytest.raises(RecurrenceExceptionError):
            RecurrenceException(**kwargs)

    def test_rescheduled_new_start_must_be_utc(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs.update(
            kind=ExceptionKind.RESCHEDULED,
            new_start=datetime(2026, 1, 6, 11, tzinfo=ZoneInfo("Asia/Tehran")),
        )
        with pytest.raises(RecurrenceExceptionError):
            RecurrenceException(**kwargs)

    @pytest.mark.parametrize("field_name", ["exception_id", "rule_id"])
    def test_ids_must_be_uuids(self, field_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[field_name] = "not-a-uuid"
        with pytest.raises(RecurrenceExceptionError):
            RecurrenceException(**kwargs)

    def test_exception_is_immutable(self) -> None:
        exception = RecurrenceException(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            exception.kind = ExceptionKind.RESCHEDULED  # type: ignore[misc]


class TestFactories:
    def test_cancel_occurrence_binds_rule(
        self, rule: RecurrenceRule
    ) -> None:
        exception = cancel_occurrence(rule, TUESDAY_9AM, created_at=CREATED)
        assert isinstance(exception.exception_id, uuid.UUID)
        assert exception.rule_id == rule.rule_id
        assert exception.kind is ExceptionKind.CANCELLED
        assert exception.created_at == CREATED

    def test_reschedule_occurrence_binds_rule(
        self, rule: RecurrenceRule
    ) -> None:
        exception = reschedule_occurrence(
            rule,
            TUESDAY_9AM,
            TUESDAY_11AM,
            new_duration=2 * HOUR,
            created_at=CREATED,
        )
        assert exception.rule_id == rule.rule_id
        assert exception.kind is ExceptionKind.RESCHEDULED
        assert exception.new_start == TUESDAY_11AM
        assert exception.new_duration == 2 * HOUR

    def test_injectable_id_and_clock(self, rule: RecurrenceRule) -> None:
        exception_id = uuid.uuid4()
        exception = cancel_occurrence(
            rule,
            TUESDAY_9AM,
            exception_id=exception_id,
            created_at=CREATED,
        )
        assert exception.exception_id == exception_id
        assert exception.created_at == CREATED

    @pytest.mark.parametrize("factory", [cancel_occurrence, reschedule_occurrence])
    def test_factories_reject_non_rules(self, factory) -> None:
        with pytest.raises(TypeError):
            factory("not a rule", TUESDAY_9AM, created_at=CREATED)  # type: ignore[arg-type]


class TestExpandWithExceptions:
    def test_without_exceptions_matches_plain_expansion(
        self, rule: RecurrenceRule, calendar: Calendar
    ) -> None:
        events = _expand(rule, calendar)
        assert [e.start for e in events] == [
            MONDAY_9AM,
            TUESDAY_9AM,
            WEDNESDAY_9AM,
        ]

    def test_cancelled_occurrence_is_dropped(
        self, rule: RecurrenceRule, calendar: Calendar
    ) -> None:
        events = _expand(
            rule,
            calendar,
            (cancel_occurrence(rule, TUESDAY_9AM, created_at=CREATED),),
        )
        assert [e.start for e in events] == [MONDAY_9AM, WEDNESDAY_9AM]

    def test_rescheduled_occurrence_moves(
        self, rule: RecurrenceRule, calendar: Calendar
    ) -> None:
        events = _expand(
            rule,
            calendar,
            (reschedule_occurrence(rule, TUESDAY_9AM, TUESDAY_11AM, created_at=CREATED),),
        )
        assert [e.start for e in events] == [
            MONDAY_9AM,
            TUESDAY_11AM,
            WEDNESDAY_9AM,
        ]
        # Default: the rule's duration is kept.
        moved = events[1]
        assert moved.end == TUESDAY_11AM + HOUR
        assert moved.title == "Morning run"

    def test_reschedule_may_override_duration(
        self, rule: RecurrenceRule, calendar: Calendar
    ) -> None:
        events = _expand(
            rule,
            calendar,
            (
                reschedule_occurrence(
                    rule,
                    TUESDAY_9AM,
                    TUESDAY_11AM,
                    new_duration=2 * HOUR,
                    created_at=CREATED,
                ),
            ),
        )
        assert events[1].end == TUESDAY_11AM + 2 * HOUR

    def test_non_matching_exception_is_ignored(
        self, rule: RecurrenceRule, calendar: Calendar
    ) -> None:
        # An exception may reference an occurrence outside this window.
        events = _expand(
            rule,
            calendar,
            (cancel_occurrence(rule, datetime(2026, 2, 1, 9, tzinfo=UTC), created_at=CREATED),),
        )
        assert [e.start for e in events] == [
            MONDAY_9AM,
            TUESDAY_9AM,
            WEDNESDAY_9AM,
        ]

    def test_conflicting_exceptions_are_rejected(
        self, rule: RecurrenceRule, calendar: Calendar
    ) -> None:
        exceptions = (
            cancel_occurrence(rule, TUESDAY_9AM, created_at=CREATED),
            reschedule_occurrence(rule, TUESDAY_9AM, TUESDAY_11AM, created_at=CREATED),
        )
        with pytest.raises(RecurrenceExceptionError, match="conflicting"):
            _expand(rule, calendar, exceptions)

    def test_foreign_rule_exception_is_rejected(
        self, rule: RecurrenceRule, calendar: Calendar
    ) -> None:
        other = create_rule(
            calendar,
            "Evening run",
            Frequency.DAILY,
            MONDAY_9AM,
            HOUR,
            created_at=CREATED,
        )
        with pytest.raises(RecurrenceExceptionError, match="belong"):
            _expand(
                rule,
                calendar,
                (cancel_occurrence(other, TUESDAY_9AM, created_at=CREATED),),
            )

    def test_non_tuple_exceptions_are_rejected(
        self, rule: RecurrenceRule, calendar: Calendar
    ) -> None:
        with pytest.raises(RecurrenceExceptionError):
            _expand(
                rule,
                calendar,
                [cancel_occurrence(rule, TUESDAY_9AM, created_at=CREATED)],  # type: ignore[arg-type]
            )

    def test_non_exception_elements_are_rejected(
        self, rule: RecurrenceRule, calendar: Calendar
    ) -> None:
        with pytest.raises(RecurrenceExceptionError):
            _expand(rule, calendar, ("Tuesday",))  # type: ignore[arg-type]

    def test_events_are_calendar_events(
        self, rule: RecurrenceRule, calendar: Calendar
    ) -> None:
        events = _expand(rule, calendar)
        assert all(isinstance(event, CalendarEvent) for event in events)
        assert all(event.calendar_id == calendar.calendar_id for event in events)
