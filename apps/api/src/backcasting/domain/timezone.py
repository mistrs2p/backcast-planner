"""Timezone handling.

"Timezone-aware operations are mandatory" (``docs/05-CALENDAR-MODEL.md``)
and "Persisted instants use UTC; user timezone is used for
interpretation/display" (``docs/10-TECHNICAL-ARCHITECTURE.md``). This
module is the single home for those semantics:

- :func:`require_utc` validates that a datetime is a UTC instant —
  the check every entity and operation shares (pass the caller's error
  class so each module keeps its typed errors).
- :func:`to_utc` normalizes any aware instant to UTC; naive datetimes
  are rejected, never guessed.
- :func:`local_time` renders a UTC instant as a zone's wall-clock time
  (interpretation/display).
- :func:`instant_from_wall_clock` builds the UTC instant for a local
  wall-clock time, preserving wall-clock semantics across DST
  transitions (ambiguous times resolve to ``fold``).
- :func:`local_time_kind` classifies a local wall-clock time as
  UNAMBIGUOUS, AMBIGUOUS (DST fall-back repeats it) or NONEXISTENT
  (DST spring-forward skips it).
- :func:`week_bounds` returns the Monday-anchored week of an instant in
  a zone, as UTC instants — the accrual window for weekly quotas and
  capacity. A DST-transition week is 167 or 169 hours long, which is
  the correct length of that local week.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

UTC = timezone.utc


class TimezoneError(ValueError):
    """Raised when a timezone invariant is violated."""


def require_utc(
    name: str,
    value: datetime,
    *,
    error: type[ValueError] = TimezoneError,
) -> None:
    """Require that ``value`` is a timezone-aware UTC datetime.

    Raises ``error`` (a ValueError subclass, defaulting to
    :class:`TimezoneError`) so callers keep their typed errors.
    """
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise error(f"{name} must be timezone-aware")
    if value.utcoffset() != UTC.utcoffset(value):
        raise error(f"{name} must be in UTC")


def to_utc(
    value: datetime,
    *,
    name: str = "value",
    error: type[ValueError] = TimezoneError,
) -> datetime:
    """Normalize an aware datetime to UTC.

    Naive datetimes are rejected — a missing zone is never guessed.
    """
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise error(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def local_time(instant: datetime, tz: ZoneInfo) -> datetime:
    """Render a UTC instant as ``tz``'s wall-clock time (display)."""
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise TimezoneError("instant must be timezone-aware")
    if not isinstance(tz, ZoneInfo):
        raise TimezoneError("tz must be a ZoneInfo")
    return instant.astimezone(tz)


def instant_from_wall_clock(
    day: date, wall: time, tz: ZoneInfo, *, fold: int = 0
) -> datetime:
    """Build the UTC instant for a local wall-clock time in ``tz``.

    Wall-clock semantics: the same local time maps to different UTC
    instants on either side of a DST transition. Ambiguous local times
    (fall-back) resolve to the given ``fold`` (0 = first occurrence).
    """
    if not isinstance(day, date):
        raise TimezoneError("day must be a date")
    if not isinstance(wall, time) or wall.tzinfo is not None:
        raise TimezoneError("wall must be a naive wall-clock time")
    if not isinstance(tz, ZoneInfo):
        raise TimezoneError("tz must be a ZoneInfo")
    naive_wall = wall.replace(fold=fold)
    return datetime.combine(day, naive_wall, tzinfo=tz).astimezone(UTC)


class LocalTimeKind(str, Enum):
    """How a local wall-clock time relates to DST in a zone."""

    UNAMBIGUOUS = "unambiguous"
    AMBIGUOUS = "ambiguous"
    NONEXISTENT = "nonexistent"


def local_time_kind(day: date, wall: time, tz: ZoneInfo) -> LocalTimeKind:
    """Classify a local wall-clock time in ``tz``.

    AMBIGUOUS: the fall-back transition repeats it (both folds map to
    different instants). NONEXISTENT: the spring-forward transition
    skips it. UNAMBIGUOUS: everything else.
    """
    if not isinstance(day, date):
        raise TimezoneError("day must be a date")
    if not isinstance(wall, time) or wall.tzinfo is not None:
        raise TimezoneError("wall must be a naive wall-clock time")
    if not isinstance(tz, ZoneInfo):
        raise TimezoneError("tz must be a ZoneInfo")
    naive = datetime.combine(day, wall)
    early = naive.replace(fold=0, tzinfo=tz).astimezone(UTC)
    late = naive.replace(fold=1, tzinfo=tz).astimezone(UTC)
    if early.astimezone(tz).replace(tzinfo=None) != naive:
        return LocalTimeKind.NONEXISTENT
    if late.astimezone(tz).replace(tzinfo=None) != naive:
        return LocalTimeKind.NONEXISTENT
    if early != late:
        return LocalTimeKind.AMBIGUOUS
    return LocalTimeKind.UNAMBIGUOUS


def week_bounds(instant: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The Monday-anchored week containing ``instant``, as UTC instants.

    The week starts Monday 00:00 local time in ``tz``; the returned
    ``[start, end)`` bounds are UTC instants per the persistence rule.
    """
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise TimezoneError("instant must be timezone-aware")
    if not isinstance(tz, ZoneInfo):
        raise TimezoneError("tz must be a ZoneInfo")
    local = instant.astimezone(tz)
    monday = local.date() - timedelta(days=local.weekday())
    start = datetime.combine(monday, time(0, 0), tzinfo=tz).astimezone(UTC)
    end = datetime.combine(
        monday + timedelta(weeks=1), time(0, 0), tzinfo=tz
    ).astimezone(UTC)
    return start, end
