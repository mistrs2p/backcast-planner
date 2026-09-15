"""Preference domain model.

A Preference is a *soft* scheduling inclination — the layer after
capacity in the scheduling hierarchy ("… → capacity → soft
preferences → optimization", docs/05-CALENDAR-MODEL.md). Unlike a
Constraint, a preference may be violated: it guides how candidate
slots are ranked, never whether they are allowed.

A preference names a weekly wall-clock window (the same shape as an
Availability Window) and a direction:

- ``PREFER`` — slots inside the window are better;
- ``AVOID`` — slots inside the window are worse.

The ``weight`` (1–5) says how much the preference matters — the
scheduler's optimization combines direction, weight, and overlap.

Rules:

- IDs are UUIDs; ``calendar_id`` references the owning calendar
  ("User owns … preferences", docs/03).
- ``weekdays`` is a non-empty set of weekdays (0 = Monday … 6 = Sunday).
- ``start_time``/``end_time`` are naive local wall-clock times with
  ``start_time < end_time`` (no cross-midnight windows in the MVP).
- ``timezone`` is a valid :class:`zoneinfo.ZoneInfo` anchoring the
  wall-clock times (defaults to the calendar's home zone).
- ``weight`` is an integer 1–5; ``title`` is optional free text
  ≤ 200 characters.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.

:func:`preference_windows` expands the window pattern into UTC
intervals over a range (DST-aware, clipped, chronological);
:func:`applies_to` reports whether a candidate interval touches the
window — the deterministic primitive the optimizer scores.
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
MIN_WEIGHT = 1
MAX_WEIGHT = 5


class PreferenceError(ValueError):
    """Raised when a preference invariant is violated."""


class PreferenceDirection(str, Enum):
    """What a window means for scheduling."""

    PREFER = "prefer"
    AVOID = "avoid"


@dataclass(frozen=True)
class Preference:
    """A soft inclination about when work is scheduled."""

    preference_id: uuid.UUID
    calendar_id: uuid.UUID
    direction: PreferenceDirection
    weekdays: frozenset[int]
    start_time: time
    end_time: time
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    weight: int = 3
    title: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.preference_id, uuid.UUID):
            raise PreferenceError("preference_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise PreferenceError("calendar_id must be a UUID")
        if not isinstance(self.direction, PreferenceDirection):
            raise PreferenceError("direction must be a PreferenceDirection")
        weekdays = frozenset(self.weekdays)
        if not weekdays:
            raise PreferenceError("weekdays must not be empty")
        for weekday in weekdays:
            if isinstance(weekday, bool) or not isinstance(weekday, int):
                raise PreferenceError("weekdays must contain integers")
            if weekday not in VALID_WEEKDAYS:
                raise PreferenceError(
                    "weekdays must contain weekdays 0 (Monday) to 6 (Sunday)"
                )
        object.__setattr__(self, "weekdays", weekdays)
        for time_name in ("start_time", "end_time"):
            wall_time = getattr(self, time_name)
            if not isinstance(wall_time, time):
                raise PreferenceError(f"{time_name} must be a datetime.time")
            if wall_time.tzinfo is not None:
                raise PreferenceError(
                    f"{time_name} must be a naive local wall-clock time"
                )
        if self.end_time <= self.start_time:
            raise PreferenceError(
                "end_time must be after start_time"
                " (preferences do not cross midnight)"
            )
        if not isinstance(self.timezone, ZoneInfo):
            raise PreferenceError("timezone must be a ZoneInfo")
        if isinstance(self.weight, bool) or not isinstance(self.weight, int):
            raise PreferenceError("weight must be an integer")
        if not MIN_WEIGHT <= self.weight <= MAX_WEIGHT:
            raise PreferenceError(
                f"weight must be between {MIN_WEIGHT} and {MAX_WEIGHT}"
            )
        title = self.title
        if title is None:
            title = ""
        if not isinstance(title, str):
            raise PreferenceError("title must be a string")
        if len(title) > MAX_TITLE_LENGTH:
            raise PreferenceError(
                f"title must be at most {MAX_TITLE_LENGTH} characters"
            )
        object.__setattr__(self, "title", title)
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise PreferenceError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise PreferenceError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise PreferenceError("updated_at must not precede created_at")


def create_preference(
    calendar: Calendar,
    direction: PreferenceDirection,
    weekdays: frozenset[int] | set[int],
    start_time: time,
    end_time: time,
    *,
    weight: int = 3,
    timezone: ZoneInfo | None = None,
    title: str = "",
    preference_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Preference:
    """Create a preference on ``calendar``.

    ``timezone`` anchors the wall-clock times and defaults to the
    calendar's home timezone.
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    now = created_at if created_at is not None else datetime.now(UTC)
    return Preference(
        preference_id=preference_id if preference_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        direction=direction,
        weekdays=frozenset(weekdays),
        start_time=start_time,
        end_time=end_time,
        timezone=timezone if timezone is not None else calendar.timezone,
        weight=weight,
        title=title,
        created_at=now,
        updated_at=now,
    )


def preference_windows(
    preference: Preference,
    *,
    range_start: datetime,
    range_end: datetime,
) -> tuple[tuple[datetime, datetime], ...]:
    """Expand the preference's window pattern into UTC intervals.

    Local wall-clock times are preserved across DST transitions;
    intervals are clipped to ``[range_start, range_end)`` and returned
    in chronological order, non-empty only.
    """
    if not isinstance(preference, Preference):
        raise TypeError("preference must be a Preference")
    require_utc("range_start", range_start, error=PreferenceError)
    require_utc("range_end", range_end, error=PreferenceError)
    if range_end <= range_start:
        raise PreferenceError("range_end must be after range_start")

    tz = preference.timezone
    first_date = range_start.astimezone(tz).date()
    last_date = range_end.astimezone(tz).date()
    windows: list[tuple[datetime, datetime]] = []
    day: date = first_date
    while day <= last_date:
        if day.weekday() in preference.weekdays:
            local_start = datetime.combine(day, preference.start_time, tzinfo=tz)
            local_end = datetime.combine(day, preference.end_time, tzinfo=tz)
            start = max(local_start.astimezone(UTC), range_start)
            end = min(local_end.astimezone(UTC), range_end)
            if start < end:
                windows.append((start, end))
        day += timedelta(days=1)
    return tuple(windows)


def applies_to(preference: Preference, start: datetime, end: datetime) -> bool:
    """Whether the interval ``[start, end)`` touches the preference's window.

    Half-open semantics: an interval ending exactly as a window begins
    (or starting exactly as one ends) does not apply.
    """
    require_utc("start", start, error=PreferenceError)
    require_utc("end", end, error=PreferenceError)
    if end <= start:
        raise PreferenceError("end must be after start")
    return any(
        window_start < end and start < window_end
        for window_start, window_end in preference_windows(
            preference, range_start=start, range_end=end
        )
    )
