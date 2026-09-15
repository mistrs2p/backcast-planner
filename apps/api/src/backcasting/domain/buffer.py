"""Buffer domain model.

The Buffer is the planning discipline's conservatism layer. The
feasibility rule is "Required Workload + Buffer ≤ usable Capacity"
(docs/04-BACKCASTING-MODEL.md): the plan is not allowed to consume
everything the calendar might deliver — a deliberate reserve is held
back for the friction reality always adds (interruptions,
underestimates, life).

The split of labor across the capacity models:

- effective capacity may exceed the plan when history over-delivers —
  that is real signal, deliberately *not* capped;
- the buffer is where conservatism lives. It reserves a fraction of
  usable capacity before the feasibility comparison, so the plan only
  ever commits to ``capacity × (1 − ratio)``.

Rules:

- ``ratio`` is a fraction in ``[0, 1)`` — 0 reserves nothing, and a
  full reserve is not a buffer but abstention, so 1 is rejected.
- ``period_start``/``period_end`` are UTC bounds with
  ``period_end > period_start``; the buffer policy is defined per
  period, like every other capacity record.
- ``title`` is optional free text ≤ 200 characters;
  ``created_at``/``updated_at`` are timezone-aware UTC with
  ``updated_at ≥ created_at``.

:func:`reserved_amount` and :func:`usable_amount` apply the ratio to
an amount; :func:`apply_buffer` pairs a buffer with an
:class:`~backcasting.domain.effective_capacity.EffectiveCapacity`
record of the same calendar and period, yielding the
:class:`BufferedCapacity` the feasibility rule consumes.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backcasting.domain.calendar import Calendar
from backcasting.domain.effective_capacity import EffectiveCapacity
from backcasting.domain.timezone import UTC, require_utc

MAX_TITLE_LENGTH = 200


class BufferError(ValueError):
    """Raised when a buffer invariant is violated."""


@dataclass(frozen=True)
class Buffer:
    """A deliberate reserve held back from usable capacity."""

    buffer_id: uuid.UUID
    calendar_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    ratio: float
    title: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.buffer_id, uuid.UUID):
            raise BufferError("buffer_id must be a UUID")
        if not isinstance(self.calendar_id, uuid.UUID):
            raise BufferError("calendar_id must be a UUID")
        require_utc("period_start", self.period_start, error=BufferError)
        require_utc("period_end", self.period_end, error=BufferError)
        if self.period_end <= self.period_start:
            raise BufferError("period_end must be after period_start")
        ratio = self.ratio
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            raise BufferError("ratio must be a number")
        if not math.isfinite(ratio):
            raise BufferError("ratio must be finite")
        if not 0 <= ratio < 1:
            raise BufferError(
                "ratio must be at least 0 and less than 1"
                " (a full reserve is not a buffer)"
            )
        object.__setattr__(self, "ratio", float(ratio))
        title = self.title
        if title is None:
            title = ""
        if not isinstance(title, str):
            raise BufferError("title must be a string")
        if len(title) > MAX_TITLE_LENGTH:
            raise BufferError(f"title must be at most {MAX_TITLE_LENGTH} characters")
        object.__setattr__(self, "title", title)
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise BufferError(f"{stamp_name} must be timezone-aware")
            if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                raise BufferError(f"{stamp_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise BufferError("updated_at must not precede created_at")


@dataclass(frozen=True)
class BufferedCapacity:
    """An effective capacity with its buffer applied.

    The record the feasibility rule consumes: the effective (usable)
    amount, the reserved slice, and what remains committable.
    """

    effective: EffectiveCapacity
    buffer: Buffer
    reserved_amount: timedelta
    usable_amount: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.effective, EffectiveCapacity):
            raise BufferError("effective must be an EffectiveCapacity")
        if not isinstance(self.buffer, Buffer):
            raise BufferError("buffer must be a Buffer")
        if self.buffer.calendar_id != self.effective.calendar_id:
            raise BufferError("buffer does not belong to this calendar")
        if (
            self.buffer.period_start != self.effective.period_start
            or self.buffer.period_end != self.effective.period_end
        ):
            raise BufferError("buffer must cover the same period as the capacity")
        for amount_name in ("reserved_amount", "usable_amount"):
            amount = getattr(self, amount_name)
            if not isinstance(amount, timedelta) or amount < timedelta(0):
                raise BufferError(f"{amount_name} must be a non-negative timedelta")


def create_buffer(
    calendar: Calendar,
    ratio: float,
    *,
    period_start: datetime,
    period_end: datetime,
    title: str = "",
    buffer_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Buffer:
    """Create a buffer policy on ``calendar`` for a period.

    ``ratio`` is the fraction of usable capacity held in reserve.
    """
    if not isinstance(calendar, Calendar):
        raise TypeError("calendar must be a Calendar")
    now = created_at if created_at is not None else datetime.now(UTC)
    return Buffer(
        buffer_id=buffer_id if buffer_id is not None else uuid.uuid4(),
        calendar_id=calendar.calendar_id,
        period_start=period_start,
        period_end=period_end,
        ratio=ratio,
        title=title,
        created_at=now,
        updated_at=now,
    )


def reserved_amount(buffer: Buffer, amount: timedelta) -> timedelta:
    """The slice of ``amount`` the buffer holds back."""
    if not isinstance(buffer, Buffer):
        raise TypeError("buffer must be a Buffer")
    if not isinstance(amount, timedelta) or amount < timedelta(0):
        raise BufferError("amount must be a non-negative timedelta")
    return timedelta(seconds=amount.total_seconds() * buffer.ratio)


def usable_amount(buffer: Buffer, amount: timedelta) -> timedelta:
    """What remains of ``amount`` after the buffer's reserve."""
    reserved = reserved_amount(buffer, amount)
    remaining = amount - reserved
    # Float rounding can only drive this to zero (ratio < 1), never below.
    return remaining if remaining > timedelta(0) else timedelta(0)


def apply_buffer(buffer: Buffer, effective: EffectiveCapacity) -> BufferedCapacity:
    """Pair ``buffer`` with the effective capacity record it applies to.

    Both must describe the same calendar and the same period — a
    reserve against another period's capacity reserves nothing.
    """
    if not isinstance(buffer, Buffer):
        raise TypeError("buffer must be a Buffer")
    if not isinstance(effective, EffectiveCapacity):
        raise TypeError("effective must be an EffectiveCapacity")
    return BufferedCapacity(
        effective=effective,
        buffer=buffer,
        reserved_amount=reserved_amount(buffer, effective.amount),
        usable_amount=usable_amount(buffer, effective.amount),
    )
