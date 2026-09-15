"""Constraint domain model.

A Constraint is a *hard* restriction on when work may be scheduled —
the first layer of the scheduling hierarchy ("Hard constraints →
existing commitments → …", docs/05-CALENDAR-MODEL.md) and the one rule
testing holds absolute: "Hard constraints are never violated"
(docs/13-TESTING.md). Violating one is the `HARD_CONSTRAINT` failure
reason (docs/06).

Two kinds cover the MVP:

- ``BLOCKED_RANGE`` — a fixed UTC interval nothing may be scheduled
  in (an on-call window, a trip).
- ``BLOCKED_WEEKLY`` — a weekly wall-clock pattern nothing may be
  scheduled in ("no work before 10:00", "weekends are sacred"),
  anchored to a timezone with local times preserved across DST —
  the mirror image of an Availability Window.

Rules:

- IDs are UUIDs; ``calendar_id`` references the owning calendar
  ("User owns … constraints", docs/03).
- ``title`` is optional free text ≤ 200 characters.
- BLOCKED_RANGE requires UTC ``start``/``end`` with ``end > start``
  and rejects the weekly fields; BLOCKED_WEEKLY requires a non-empty
  weekday set, naive local ``start_time < end_time`` (no cross-midnight
  blocks in the MVP), and a ZoneInfo anchor, and rejects the range
  fields.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.

:func:`blocked_intervals` expands a constraint into the UTC intervals
it blocks over a range (chronological, clipped to the range);
:func:`is_blocked` reports whether a candidate interval violates it
(half-open semantics: scheduling to end exactly as a block begins is
allowed).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from backcasting.domain.calendar import Calendar
from backcasting.domain.timezone import UTC, require_utc

MAX_TITLE_LENGTH = 200
VALID_WEEKDAYS = frozenset(range(7))


class ConstraintError(ValueError):
    """Raised when a constraint invariant is violated."""


class ConstraintKind(str, Enum):
    """The shape of a hard constraint."""

    BLOCKED_RANGE = "blocked_range"
    BLOCKED_WEEKLY = "blocked_weekly"


@dataclass(frozen=True)
class Constraint:
    """A hard restriction on when work may be scheduled."""

    constraint_id: uuid.UUID
    calendar_id: uuid.UUID
    kind: ConstraintKind
    title: str = ""
    start: datetime | None = None
    end: datetime | None = None
    weekdays: frozenset[int] = frozenset()
    start_time: time | None = None
    end_time: time | None = None
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.constraint_id, uuid.UUID):
            raise ConstraintError("constraint_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise ConstraintError("calendar_id must be a UUID")
        if not isinstance(self.kind, ConstraintKind):
            raise ConstraintError("kind must be a ConstraintKind")
        title = self.title
        if title is None:
            title = ""
        if not isinstance(title, str):
            raise ConstraintError("title must be a string")
        if len(title) > MAX_TITLE_LENGTH:
            raise ConstraintError(
                f"title must be at most {MAX_TITLE_LENGTH} characters"
            )
        object.__setattr__(self, "title", title)

        if self.kind is ConstraintKind.BLOCKED_RANGE:
            require_utc("start", self.start, error=ConstraintError)
            require_utc("end", self.end, error=ConstraintError)
            if self.end <= self.start:
                raise ConstraintError("end must be after start")
            if self.weekdays:
                raise ConstraintError(
                    "weekdays are only valid for BLOCKED_WEEKLY constraints"
                )
            if self.start_time is not None or self.end_time is not None:
                raise ConstraintError(
                    "start_time/end_time are only valid for BLOCKED_WEEKLY"
                    " constraints"
                )
        else:  # BLOCKED_WEEKLY
            if self.start is not None or self.end is not None:
                raise ConstraintError(
                    "start/end are only valid for BLOCKED_RANGE constraints"
                )
            weekdays = frozenset(self.weekdays)
            if not weekdays:
                raise ConstraintError("weekdays must not be empty")
            for weekday in weekdays:
                if isinstance(weekday, bool) or not isinstance(weekday, int):
                    raise ConstraintError("weekdays must contain integers")
                if weekday not in VALID_WEEKDAYS:
                    raise ConstraintError(
                        "weekdays must contain weekdays 0 (Monday) to 6 (Sunday)"
                    )
            object.__setattr__(self, "weekdays", weekdays)
            for time_name in ("start_time", "end_time"):
                wall_time = getattr(self, time_name)
                if not isinstance(wall_time, time):
                    raise ConstraintError(
                        f"{time_name} must be a datetime.time"
                    )
                if wall_time.tzinfo is not None:
                    raise ConstraintError(
                        f"{time_name} must be a naive local wall-clock time"
                    )
            if self.end_time <= self.start_time:
                raise ConstraintError(
                    "end_time must be after start_time"
                    " (constraints do not cross midnight)"
                )
        if not isinstance(self.timezone, ZoneInfo):
            raise ConstraintError("timezone must be a ZoneInfo")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise ConstraintError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise ConstraintError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise ConstraintError("updated_at must not precede created_at")


def create_constraint_range(
    calendar: Calendar,
    title: str,
    start: datetime,
    end: datetime,
    *,
    constraint_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Constraint:
    """Create a fixed blocked range on ``calendar``."""
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    now = created_at if created_at is not None else datetime.now(UTC)
    return Constraint(
        constraint_id=constraint_id if constraint_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        kind=ConstraintKind.BLOCKED_RANGE,
        title=title,
        start=start,
        end=end,
        created_at=now,
        updated_at=now,
    )


def create_constraint_weekly(
    calendar: Calendar,
    title: str,
    weekdays: frozenset[int] | set[int],
    start_time: time,
    end_time: time,
    *,
    timezone: ZoneInfo | None = None,
    constraint_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Constraint:
    """Create a weekly wall-clock block on ``calendar``.

    ``timezone`` anchors the wall-clock times and defaults to the
    calendar's home timezone.
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    now = created_at if created_at is not None else datetime.now(UTC)
    return Constraint(
        constraint_id=constraint_id if constraint_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        kind=ConstraintKind.BLOCKED_WEEKLY,
        title=title,
        weekdays=frozenset(weekdays),
        start_time=start_time,
        end_time=end_time,
        timezone=timezone if timezone is not None else calendar.timezone,
        created_at=now,
        updated_at=now,
    )


def blocked_intervals(
    constraint: Constraint,
    *,
    range_start: datetime,
    range_end: datetime,
) -> tuple[tuple[datetime, datetime], ...]:
    """Expand a constraint into the UTC intervals it blocks.

    Intervals are clipped to ``[range_start, range_end)`` and returned
    in chronological order; only non-empty intervals appear.
    """
    if not isinstance(constraint, Constraint):
        raise TypeError("constraint must be a Constraint")
    require_utc("range_start", range_start, error=ConstraintError)
    require_utc("range_end", range_end, error=ConstraintError)
    if range_end <= range_start:
        raise ConstraintError("range_end must be after range_start")

    if constraint.kind is ConstraintKind.BLOCKED_RANGE:
        start = max(constraint.start, range_start)
        end = min(constraint.end, range_end)
        return ((start, end),) if start < end else ()

    tz = constraint.timezone
    first_date = range_start.astimezone(tz).date()
    last_date = range_end.astimezone(tz).date()
    blocked: list[tuple[datetime, datetime]] = []
    day: date = first_date
    while day <= last_date:
        if day.weekday() in constraint.weekdays:
            local_start = datetime.combine(day, constraint.start_time, tzinfo=tz)
            local_end = datetime.combine(day, constraint.end_time, tzinfo=tz)
            start = max(local_start.astimezone(UTC), range_start)
            end = min(local_end.astimezone(UTC), range_end)
            if start < end:
                blocked.append((start, end))
        day += timedelta(days=1)
    return tuple(blocked)


def is_blocked(constraint: Constraint, start: datetime, end: datetime) -> bool:
    """Whether the interval ``[start, end)`` violates the constraint.

    Half-open semantics: an interval ending exactly as a block begins
    (or starting exactly as one ends) is allowed.
    """
    require_utc("start", start, error=ConstraintError)
    require_utc("end", end, error=ConstraintError)
    if end <= start:
        raise ConstraintError("end must be after start")
    return any(
        blocked_start < end and start < blocked_end
        for blocked_start, blocked_end in blocked_intervals(
            constraint, range_start=start, range_end=end
        )
    )
