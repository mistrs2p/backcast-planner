"""Floating rest domain model.

"Floating rest supports quotas without fixed weekdays"
(``docs/05-CALENDAR-MODEL.md``): a user commits to an amount of rest
per week, but — unlike a recurring rule — not to particular days. The
quota floats: it is satisfied wherever the rest actually happens.

Rules:

- IDs are UUIDs; ``calendar_id`` references the calendar the quota
  belongs to.
- ``title`` is non-empty, stripped, ≤ 200 characters.
- ``weekly_quota`` is a positive timedelta — the MVP period is one
  week (the spec contrasts floating rest with *fixed weekdays*, so the
  week is the natural accrual window).
- ``created_at``/``updated_at`` are timezone-aware UTC;
  ``updated_at ≥ created_at``.
- :func:`evaluate_rest` measures satisfaction from arbitrary rest
  intervals: overlapping (and touching) intervals are merged before
  summing, so the same rest time is never counted twice. Consumed time
  may exceed the quota — ``remaining`` goes negative, ``satisfied``
  stays true.

Where the rest is *placed* on the calendar is the scheduler's concern
(the scheduling epic); this module only defines the quota and measures
it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backcasting.domain.calendar import Calendar
from backcasting.domain.timezone import require_utc

MAX_TITLE_LENGTH = 200


class FloatingRestError(ValueError):
    """Raised when a floating-rest invariant is violated."""


@dataclass(frozen=True)
class FloatingRest:
    """A weekly rest quota that floats across weekdays."""

    rest_id: uuid.UUID
    calendar_id: uuid.UUID
    title: str
    weekly_quota: timedelta
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.rest_id, uuid.UUID):
            raise FloatingRestError("rest_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise FloatingRestError("calendar_id must be a UUID")
        title = self.title
        if not isinstance(title, str) or not title.strip():
            raise FloatingRestError("title must be a non-empty string")
        if len(title.strip()) > MAX_TITLE_LENGTH:
            raise FloatingRestError(
                f"title must be at most {MAX_TITLE_LENGTH} characters"
            )
        object.__setattr__(self, "title", title.strip())
        if (
            not isinstance(self.weekly_quota, timedelta)
            or self.weekly_quota <= timedelta(0)
        ):
            raise FloatingRestError("weekly_quota must be a positive timedelta")
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise FloatingRestError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise FloatingRestError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise FloatingRestError("updated_at must not precede created_at")


def create_floating_rest(
    calendar: Calendar,
    title: str,
    weekly_quota: timedelta,
    *,
    rest_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> FloatingRest:
    """Create a floating rest quota on ``calendar``."""
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    now = created_at if created_at is not None else datetime.now(timezone.utc)
    return FloatingRest(
        rest_id=rest_id if rest_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        title=title,
        weekly_quota=weekly_quota,
        created_at=now,
        updated_at=now,
    )


@dataclass(frozen=True)
class RestBalance:
    """The measured state of a floating rest quota."""

    quota: timedelta
    consumed: timedelta
    remaining: timedelta
    satisfied: bool


def evaluate_rest(
    rest: FloatingRest,
    intervals: tuple[tuple[datetime, datetime], ...],
) -> RestBalance:
    """Measure a floating rest quota against rest intervals.

    ``intervals`` are ``(start, end)`` pairs of timezone-aware UTC
    instants with ``end > start``; they may arrive in any order.
    Overlapping and touching intervals are merged first, so the same
    rest time is never counted twice.
    """
    if not isinstance(rest, FloatingRest):
        raise TypeError("rest must be a FloatingRest")
    if not isinstance(intervals, tuple):
        raise FloatingRestError("intervals must be a tuple of (start, end) pairs")
    spans: list[tuple[datetime, datetime]] = []
    for interval in intervals:
        if not isinstance(interval, tuple) or len(interval) != 2:
            raise FloatingRestError("intervals must be (start, end) pairs")
        start, end = interval
        require_utc("interval start", start, error=FloatingRestError)
        require_utc("interval end", end, error=FloatingRestError)
        if end <= start:
            raise FloatingRestError("interval end must be after start")
        spans.append((start, end))

    consumed = timedelta(0)
    merged: list[list[datetime]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    for start, end in merged:
        consumed += end - start

    return RestBalance(
        quota=rest.weekly_quota,
        consumed=consumed,
        remaining=rest.weekly_quota - consumed,
        satisfied=consumed >= rest.weekly_quota,
    )
