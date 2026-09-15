"""Recurrence rule domain model.

A Recurrence Rule places a repeating event pattern on a calendar
(``docs/05-CALENDAR-MODEL.md``): how habits and routines
(``docs/03-DOMAIN-MODEL.md``) materialize as calendar events. Rules
expand deterministically into :class:`CalendarEvent` occurrences; the
exceptions that override individual occurrences are a separate concept
(the exceptions task).

Rules:

- IDs are UUIDs; ``calendar_id`` references the calendar the rule
  belongs to.
- ``title``/``description`` are the template for generated events
  (non-empty stripped ≤ 200 / optional ≤ 5000 characters).
- Frequency is DAILY or WEEKLY (MVP); ``interval`` ≥ 1 repeats every N
  days/weeks. WEEKLY rules may name weekdays via ``by_weekday``
  (0 = Monday … 6 = Sunday); an empty set means the weekday of
  ``starts_on``. Naming weekdays on a DAILY rule is rejected.
- ``starts_on`` is a timezone-aware UTC instant; expansion preserves its
  *local* time of day in ``timezone`` (wall-clock semantics), so a
  9:00 London occurrence stays 9:00 across a DST transition even though
  its UTC instant shifts. Ambiguous local times (DST fall-back) resolve
  to the first occurrence (``fold=0``).
- ``duration`` is a positive timedelta per occurrence; ``until``
  (exclusive of nothing — it bounds occurrence *starts*) is optional
  and must lie after ``starts_on``.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    CalendarEvent,
    create_event,
)
from backcasting.domain.timezone import UTC, require_utc

VALID_WEEKDAYS = frozenset(range(7))


class RecurrenceError(ValueError):
    """Raised when a recurrence rule invariant is violated."""


class Frequency(str, Enum):
    """Supported recurrence frequencies (MVP)."""

    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass(frozen=True)
class RecurrenceRule:
    """A repeating event pattern on a calendar."""

    rule_id: uuid.UUID
    calendar_id: uuid.UUID
    title: str
    frequency: Frequency
    starts_on: datetime
    duration: timedelta
    interval: int = 1
    by_weekday: frozenset[int] = frozenset()
    until: datetime | None = None
    description: str = ""
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, uuid.UUID):
            raise RecurrenceError("rule_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise RecurrenceError("calendar_id must be a UUID")
        title = self.title
        if not isinstance(title, str) or not title.strip():
            raise RecurrenceError("title must be a non-empty string")
        if len(title.strip()) > MAX_TITLE_LENGTH:
            raise RecurrenceError(
                f"title must be at most {MAX_TITLE_LENGTH} characters"
            )
        object.__setattr__(self, "title", title.strip())
        if not isinstance(self.frequency, Frequency):
            raise RecurrenceError("frequency must be a Frequency")
        require_utc("starts_on", self.starts_on, error=RecurrenceError)
        if not isinstance(self.duration, timedelta) or self.duration <= timedelta(0):
            raise RecurrenceError("duration must be a positive timedelta")
        if isinstance(self.interval, bool) or not isinstance(self.interval, int):
            raise RecurrenceError("interval must be an integer")
        if self.interval < 1:
            raise RecurrenceError("interval must be at least 1")
        by_weekday = frozenset(self.by_weekday)
        for weekday in by_weekday:
            if isinstance(weekday, bool) or not isinstance(weekday, int):
                raise RecurrenceError("by_weekday must contain integers")
            if weekday not in VALID_WEEKDAYS:
                raise RecurrenceError(
                    "by_weekday must contain weekdays 0 (Monday) to 6 (Sunday)"
                )
        object.__setattr__(self, "by_weekday", by_weekday)
        if self.frequency is Frequency.DAILY and by_weekday:
            raise RecurrenceError("by_weekday is only valid for WEEKLY rules")
        if self.until is not None:
            require_utc("until", self.until, error=RecurrenceError)
            if self.until <= self.starts_on:
                raise RecurrenceError("until must be after starts_on")
        description = self.description
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise RecurrenceError("description must be a string")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise RecurrenceError(
                f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        object.__setattr__(self, "description", description)
        if not isinstance(self.timezone, ZoneInfo):
            raise RecurrenceError("timezone must be a ZoneInfo")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise RecurrenceError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise RecurrenceError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise RecurrenceError("updated_at must not precede created_at")


def create_rule(
    calendar: Calendar,
    title: str,
    frequency: Frequency,
    starts_on: datetime,
    duration: timedelta,
    *,
    interval: int = 1,
    by_weekday: frozenset[int] | set[int] = frozenset(),
    until: datetime | None = None,
    description: str = "",
    timezone: ZoneInfo | None = None,
    rule_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> RecurrenceRule:
    """Create a recurrence rule on ``calendar``.

    ``timezone`` anchors wall-clock expansion and defaults to the
    calendar's home timezone.
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    now = created_at if created_at is not None else datetime.now(UTC)
    return RecurrenceRule(
        rule_id=rule_id if rule_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        title=title,
        frequency=frequency,
        starts_on=starts_on,
        duration=duration,
        interval=interval,
        by_weekday=frozenset(by_weekday),
        until=until,
        description=description,
        timezone=timezone if timezone is not None else calendar.timezone,
        created_at=now,
        updated_at=now,
    )


def occurrences(
    rule: RecurrenceRule,
    *,
    window_start: datetime,
    window_end: datetime,
) -> tuple[datetime, ...]:
    """Compute the occurrence start instants inside a window.

    Occurrences start within ``[max(starts_on, window_start),
    min(until, window_end)]`` (inclusive bounds on start instants). Both
    window bounds must be timezone-aware UTC with
    ``window_end > window_start``.
    """
    if not isinstance(rule, RecurrenceRule):
        raise TypeError("rule must be a RecurrenceRule")
    require_utc("window_start", window_start, error=RecurrenceError)
    require_utc("window_end", window_end, error=RecurrenceError)
    if window_end <= window_start:
        raise RecurrenceError("window_end must be after window_start")
    effective_start = max(window_start, rule.starts_on)
    effective_end = window_end if rule.until is None else min(window_end, rule.until)
    if effective_end < effective_start:
        return ()

    anchor_local = rule.starts_on.astimezone(rule.timezone)
    time_of_day = anchor_local.time()

    def _instant(local_date: date) -> datetime:
        return datetime.combine(
            local_date, time_of_day, tzinfo=rule.timezone
        ).astimezone(timezone.utc)

    results: list[datetime] = []
    if rule.frequency is Frequency.DAILY:
        step = 0
        while True:
            start = _instant(anchor_local.date() + timedelta(days=step * rule.interval))
            if start > effective_end:
                break
            if start >= effective_start:
                results.append(start)
            step += 1
    else:  # WEEKLY
        weekdays = rule.by_weekday or frozenset({anchor_local.weekday()})
        week_start = anchor_local.date() - timedelta(days=anchor_local.weekday())
        week = 0
        exhausted = False
        while not exhausted:
            for weekday in sorted(weekdays):
                start = _instant(
                    week_start
                    + timedelta(weeks=week * rule.interval, days=weekday)
                )
                if start > effective_end:
                    exhausted = True
                    break
                if start >= effective_start:
                    results.append(start)
            week += 1
    return tuple(results)


def expand_rule(
    rule: RecurrenceRule,
    calendar: Calendar,
    *,
    window_start: datetime,
    window_end: datetime,
) -> tuple[CalendarEvent, ...]:
    """Expand a rule into calendar events within a window.

    Each occurrence becomes a :class:`CalendarEvent` carrying the rule's
    title, description, and duration. The rule must belong to
    ``calendar``.
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    if rule.calendar_id != calendar.calendar_id:
        raise RecurrenceError("rule does not belong to this calendar")
    return tuple(
        create_event(
            calendar,
            rule.title,
            start,
            start + rule.duration,
            description=rule.description,
        )
        for start in occurrences(rule, window_start=window_start, window_end=window_end)
    )
