"""Recurrence exception domain model.

"Recurring rules may have exceptions" (``docs/05-CALENDAR-MODEL.md``):
real life overrides individual occurrences of a repeating pattern. An
exception addresses an occurrence by its *original start instant* — the
deterministic identity of an expansion result — and either cancels it
or reschedules it.

Rules:

- IDs are UUIDs; ``rule_id`` references the rule the exception applies
  to.
- ``kind`` is CANCELLED or RESCHEDULED. A CANCELLED exception carries no
  replacement; a RESCHEDULED exception must carry ``new_start``
  (a timezone-aware UTC instant different from ``original_start``) and
  may override the occurrence's ``duration`` (positive timedelta).
- ``original_start``/``new_start`` are timezone-aware UTC instants.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.

:func:`expand_with_exceptions` applies a batch of exceptions to a
rule's expansion: cancelled occurrences are removed, rescheduled ones
appear at their new times (keeping the rule's title and description).
Exceptions whose ``original_start`` matches no occurrence in the
expansion window are ignored — a window clips occurrences, so an
exception may legitimately reference one outside it. Two exceptions for
the same ``original_start`` are ambiguous and rejected. Events are
returned in original occurrence order; callers sort by start for
calendar views.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent, create_event
from backcasting.domain.recurrence import RecurrenceRule, occurrences
from backcasting.domain.timezone import require_utc


class RecurrenceExceptionError(ValueError):
    """Raised when a recurrence exception invariant is violated."""


class ExceptionKind(str, Enum):
    """What an exception does to its occurrence."""

    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


@dataclass(frozen=True)
class RecurrenceException:
    """An override applied to a single occurrence of a recurrence rule."""

    exception_id: uuid.UUID
    rule_id: uuid.UUID
    kind: ExceptionKind
    original_start: datetime
    new_start: datetime | None = None
    new_duration: timedelta | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.exception_id, uuid.UUID):
            raise RecurrenceExceptionError("exception_id must be a UUID")
        if not isinstance(self.rule_id, uuid.UUID):
            raise RecurrenceExceptionError("rule_id must be a UUID")
        if not isinstance(self.kind, ExceptionKind):
            raise RecurrenceExceptionError("kind must be an ExceptionKind")
        require_utc(
            "original_start", self.original_start, error=RecurrenceExceptionError
        )
        if self.kind is ExceptionKind.CANCELLED:
            if self.new_start is not None:
                raise RecurrenceExceptionError(
                    "a cancelled occurrence has no replacement start"
                )
        else:  # RESCHEDULED
            if self.new_start is None:
                raise RecurrenceExceptionError(
                    "a rescheduled occurrence requires new_start"
                )
            require_utc("new_start", self.new_start, error=RecurrenceExceptionError)
            if self.new_start == self.original_start:
                raise RecurrenceExceptionError(
                    "new_start must differ from original_start"
                )
        if self.new_duration is not None:
            if (
                not isinstance(self.new_duration, timedelta)
                or self.new_duration <= timedelta(0)
            ):
                raise RecurrenceExceptionError(
                    "new_duration must be a positive timedelta"
                )
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise RecurrenceExceptionError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise RecurrenceExceptionError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise RecurrenceExceptionError(
                "updated_at must not precede created_at"
            )


def cancel_occurrence(
    rule: RecurrenceRule,
    original_start: datetime,
    *,
    exception_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> RecurrenceException:
    """Cancel the occurrence of ``rule`` starting at ``original_start``."""
    if not isinstance(rule, RecurrenceRule):
        raise TypeError("rule must be a RecurrenceRule")
    now = created_at if created_at is not None else datetime.now(timezone.utc)
    return RecurrenceException(
        exception_id=exception_id if exception_id is not None else uuid.uuid4(),
        rule_id=rule.rule_id,
        kind=ExceptionKind.CANCELLED,
        original_start=original_start,
        created_at=now,
        updated_at=now,
    )


def reschedule_occurrence(
    rule: RecurrenceRule,
    original_start: datetime,
    new_start: datetime,
    *,
    new_duration: timedelta | None = None,
    exception_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> RecurrenceException:
    """Move the occurrence of ``rule`` starting at ``original_start``."""
    if not isinstance(rule, RecurrenceRule):
        raise TypeError("rule must be a RecurrenceRule")
    now = created_at if created_at is not None else datetime.now(timezone.utc)
    return RecurrenceException(
        exception_id=exception_id if exception_id is not None else uuid.uuid4(),
        rule_id=rule.rule_id,
        kind=ExceptionKind.RESCHEDULED,
        original_start=original_start,
        new_start=new_start,
        new_duration=new_duration,
        created_at=now,
        updated_at=now,
    )


def expand_with_exceptions(
    rule: RecurrenceRule,
    calendar: Calendar,
    exceptions: tuple[RecurrenceException, ...],
    *,
    window_start: datetime,
    window_end: datetime,
) -> tuple[CalendarEvent, ...]:
    """Expand ``rule`` with a batch of exceptions applied.

    Cancelled occurrences are dropped; rescheduled occurrences appear at
    their new start (with the overridden duration when given, else the
    rule's). The rule must own every exception, and no two exceptions
    may address the same ``original_start``.
    """
    if not isinstance(rule, RecurrenceRule):
        raise TypeError("rule must be a RecurrenceRule")
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    if not isinstance(exceptions, tuple):
        raise RecurrenceExceptionError(
            "exceptions must be a tuple of RecurrenceException"
        )
    by_original: dict[datetime, RecurrenceException] = {}
    for exception in exceptions:
        if not isinstance(exception, RecurrenceException):
            raise RecurrenceExceptionError(
                "exceptions must be RecurrenceException instances"
            )
        if exception.rule_id != rule.rule_id:
            raise RecurrenceExceptionError(
                "exception does not belong to this rule"
            )
        if exception.original_start in by_original:
            raise RecurrenceExceptionError(
                f"conflicting exceptions for occurrence at "
                f"{exception.original_start.isoformat()}"
            )
        by_original[exception.original_start] = exception

    events: list[CalendarEvent] = []
    for start in occurrences(
        rule, window_start=window_start, window_end=window_end
    ):
        exception = by_original.get(start)
        if exception is None:
            events.append(
                create_event(
                    calendar, rule.title, start, start + rule.duration,
                    description=rule.description,
                )
            )
        elif exception.kind is ExceptionKind.CANCELLED:
            continue
        else:  # RESCHEDULED — new_start is guaranteed by construction
            duration = (
                exception.new_duration
                if exception.new_duration is not None
                else rule.duration
            )
            new_start = exception.new_start
            events.append(
                create_event(
                    calendar,
                    rule.title,
                    new_start,
                    new_start + duration,
                    description=rule.description,
                )
            )
    return tuple(events)
