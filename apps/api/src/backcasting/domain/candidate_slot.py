"""Candidate slot generation.

Scheduling "places schedulable tasks into feasible time slots"
(docs/06). Before any placement happens, the raw material must exist:
the *candidate slots* — the stretches of free time in which a task of
a given duration could fit. This module generates them; the rest of
the scheduling hierarchy (docs/05 — "Hard constraints → existing
commitments → dependencies → deadline → capacity → soft preferences
→ optimization") filters and ranks what is generated here, never
invents time.

A :class:`CandidateSlot` is a maximal free interval: merged
availability windows, minus the commitments occupying them, clipped
to the horizon, and kept only when long enough for the task. The
semantics deliberately mirror :func:`workable_time` — the shared
capacity semantics — so a slot's total always reconciles with the
planned capacity over the same range:

- overlapping and touching intervals are merged first, so no time is
  ever offered twice;
- commitments outside the availability consume nothing (an evening
  meeting does not eat working hours);
- wall-clock availability is expanded across DST transitions by
  :func:`available_intervals`.

Failure semantics: when no slot can hold the task, the result is
empty and the scheduler reports ``NO_AVAILABLE_SLOT`` (docs/06) — an
empty generation is a fact, not an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from backcasting.domain.availability import (
    AvailabilityWindow,
    available_intervals,
)
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.planned_capacity import _clip, _merge, _subtract
from backcasting.domain.timezone import require_utc


class CandidateSlotError(ValueError):
    """Raised when a candidate-slot invariant is violated."""


@dataclass(frozen=True)
class CandidateSlot:
    """A maximal free interval a task may be placed into."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        require_utc("start", self.start, error=CandidateSlotError)
        require_utc("end", self.end, error=CandidateSlotError)
        if self.end <= self.start:
            raise CandidateSlotError("slot end must be after start")

    @property
    def duration(self) -> timedelta:
        """The slot's length."""
        return self.end - self.start

    def can_fit(self, duration: timedelta) -> bool:
        """Whether a task of ``duration`` fits in this slot."""
        if not isinstance(duration, timedelta) or duration <= timedelta(0):
            raise CandidateSlotError("duration must be a strictly positive timedelta")
        return duration <= self.end - self.start


def generate_candidate_slots(
    windows: tuple[AvailabilityWindow, ...],
    events: tuple[CalendarEvent, ...] = (),
    *,
    duration: timedelta,
    range_start: datetime,
    range_end: datetime,
) -> tuple[CandidateSlot, ...]:
    """Generate the candidate slots for a task of ``duration``.

    Merged availability minus occupying commitments over
    ``[range_start, range_end)``; only intervals at least ``duration``
    long survive. Returns the slots in chronological order — maximal
    intervals, not chopped pieces: where inside a slot a task lands is
    the placement step's decision, informed by the hierarchy's later
    layers.
    """
    if not isinstance(windows, tuple):
        raise CandidateSlotError("windows must be a tuple of AvailabilityWindow")
    for window in windows:
        if not isinstance(window, AvailabilityWindow):
            raise CandidateSlotError("windows must be AvailabilityWindow instances")
    if not isinstance(events, tuple):
        raise CandidateSlotError("events must be a tuple of CalendarEvent")
    for event in events:
        if not isinstance(event, CalendarEvent):
            raise CandidateSlotError("events must be CalendarEvent instances")
    if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise CandidateSlotError("duration must be a strictly positive timedelta")
    require_utc("range_start", range_start, error=CandidateSlotError)
    require_utc("range_end", range_end, error=CandidateSlotError)
    if range_end <= range_start:
        raise CandidateSlotError("range_end must be after range_start")

    available: list[tuple[datetime, datetime]] = []
    for window in windows:
        available.extend(
            available_intervals(window, range_start=range_start, range_end=range_end)
        )
    merged_availability = _merge(available)

    committed: list[tuple[datetime, datetime]] = []
    for event in events:
        clipped = _clip(event.start, event.end, range_start, range_end)
        if clipped is not None:
            committed.append(clipped)
    merged_commitments = _merge(committed)

    slots = [
        CandidateSlot(start=start, end=end)
        for start, end in _subtract(merged_availability, merged_commitments)
        if end - start >= duration
    ]
    return tuple(slots)
