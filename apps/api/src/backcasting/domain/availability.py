"""Availability domain model.

An Availability Window is when the user *can* work
(``docs/05-CALENDAR-MODEL.md`` "Availability Window"): a weekly
wall-clock pattern such as weekday evenings. Availability is not
capacity (``docs/00-PROJECT-CONTEXT.md`` "Availability ≠ Capacity") —
capacity is what the time environment yields after commitments and
constraints, and is computed in the capacity epic from these windows.

Rules:

- IDs are UUIDs; ``calendar_id`` references the calendar the window
  belongs to.
- ``weekdays`` is a non-empty set of weekdays (0 = Monday … 6 = Sunday).
- ``start_time``/``end_time`` are naive local wall-clock times with
  ``start_time < end_time``: a window lies within a single local day
  (no cross-midnight windows in the MVP).
- ``timezone`` is a valid :class:`zoneinfo.ZoneInfo` anchoring the
  wall-clock times (defaults to the calendar's home zone).
- ``title`` is optional free text ≤ 200 characters.
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
- :func:`available_intervals` expands the pattern into UTC intervals
  over a range, preserving local wall-clock times across DST
  transitions and clipping to the range bounds.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from backcasting.domain.calendar import Calendar

MAX_TITLE_LENGTH = 200
VALID_WEEKDAYS = frozenset(range(7))


class AvailabilityError(ValueError):
    """Raised when an availability invariant is violated."""


def _require_utc(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AvailabilityError(f"{name} must be timezone-aware")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise AvailabilityError(f"{name} must be in UTC")


@dataclass(frozen=True)
class AvailabilityWindow:
    """A weekly wall-clock window when the user is available."""

    window_id: uuid.UUID
    calendar_id: uuid.UUID
    weekdays: frozenset[int]
    start_time: time
    end_time: time
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    title: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.window_id, uuid.UUID):
            raise AvailabilityError("window_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise AvailabilityError("calendar_id must be a UUID")
        weekdays = frozenset(self.weekdays)
        if not weekdays:
            raise AvailabilityError("weekdays must not be empty")
        for weekday in weekdays:
            if isinstance(weekday, bool) or not isinstance(weekday, int):
                raise AvailabilityError("weekdays must contain integers")
            if weekday not in VALID_WEEKDAYS:
                raise AvailabilityError(
                    "weekdays must contain weekdays 0 (Monday) to 6 (Sunday)"
                )
        object.__setattr__(self, "weekdays", weekdays)
        for time_name in ("start_time", "end_time"):
            wall_time = getattr(self, time_name)
            if not isinstance(wall_time, time):
                raise AvailabilityError(f"{time_name} must be a datetime.time")
            if wall_time.tzinfo is not None:
                raise AvailabilityError(
                    f"{time_name} must be a naive local wall-clock time"
                )
        if self.end_time <= self.start_time:
            raise AvailabilityError(
                "end_time must be after start_time (windows do not cross midnight)"
            )
        if not isinstance(self.timezone, ZoneInfo):
            raise AvailabilityError("timezone must be a ZoneInfo")
        title = self.title
        if title is None:
            title = ""
        if not isinstance(title, str):
            raise AvailabilityError("title must be a string")
        if len(title) > MAX_TITLE_LENGTH:
            raise AvailabilityError(
                f"title must be at most {MAX_TITLE_LENGTH} characters"
            )
        object.__setattr__(self, "title", title)
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise AvailabilityError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise AvailabilityError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise AvailabilityError("updated_at must not precede created_at")


def create_availability_window(
    calendar: Calendar,
    weekdays: frozenset[int] | set[int],
    start_time: time,
    end_time: time,
    *,
    timezone: ZoneInfo | None = None,
    title: str = "",
    window_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> AvailabilityWindow:
    """Create an availability window on ``calendar``.

    ``timezone`` anchors the wall-clock times and defaults to the
    calendar's home timezone.
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    now = created_at if created_at is not None else datetime.now(timezone.utc)
    return AvailabilityWindow(
        window_id=window_id if window_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        weekdays=frozenset(weekdays),
        start_time=start_time,
        end_time=end_time,
        timezone=timezone if timezone is not None else calendar.timezone,
        title=title,
        created_at=now,
        updated_at=now,
    )


def available_intervals(
    window: AvailabilityWindow,
    *,
    range_start: datetime,
    range_end: datetime,
) -> tuple[tuple[datetime, datetime], ...]:
    """Expand the window's weekly pattern into UTC intervals over a range.

    Every local date in the range whose weekday is selected contributes
    one interval (local wall-clock times preserved across DST
    transitions). Intervals are clipped to ``[range_start,
    range_end]``; only non-empty clipped intervals are returned, in
    chronological order.
    """
    if not isinstance(window, AvailabilityWindow):
        raise TypeError("window must be an AvailabilityWindow")
    _require_utc("range_start", range_start)
    _require_utc("range_end", range_end)
    if range_end <= range_start:
        raise AvailabilityError("range_end must be after range_start")

    tz = window.timezone
    first_date = range_start.astimezone(tz).date()
    last_date = range_end.astimezone(tz).date()

    intervals: list[tuple[datetime, datetime]] = []
    day: date = first_date
    while day <= last_date:
        if day.weekday() in window.weekdays:
            local_start = datetime.combine(day, window.start_time, tzinfo=tz)
            local_end = datetime.combine(day, window.end_time, tzinfo=tz)
            start = max(local_start.astimezone(timezone.utc), range_start)
            end = min(local_end.astimezone(timezone.utc), range_end)
            if start < end:
                intervals.append((start, end))
        day += timedelta(days=1)
    return tuple(intervals)
