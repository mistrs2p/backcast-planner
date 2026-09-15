"""Conflict resolution — deciding who yields and what happens next.

docs/06-PLANNING-SCHEDULING.md fixes the principle: "Conflict should
first be resolved through rescheduling; escalate to replanning only
when Plan-level feasibility is affected." This module is the
deterministic half of that (ADR-002): *who* yields and *which action*
follows. The actual re-placement is the rescheduling machinery; the
actual replanning is the adaptation layer's.

Who yields follows the scheduling hierarchy (docs/05: "hard
constraints → existing commitments → …"): an existing commitment
(calendar event) always displaces a task placement — commitments are
facts about the user's time, placements are plans. Between two
placements the later-starting one yields (ties: later end, then
later id) — the earliest placement is the most settled, and the rule
is deterministic regardless of input order. A placement's own task
cannot overlap itself: that state violates the placement invariant
(schedule.py) and is an error here, never quietly "resolved".

The blocked interval of a displacement is the exact overlap — the
time the yielding placement must vacate.

What happens next is :func:`resolve_displacement`: given the
displaced placement and its surviving candidate slots (already
filtered through deadline, dependencies, capacity — the caller's
pipeline), non-empty slots mean the conflict resolves through
rescheduling; empty slots mean no placement exists anywhere —
Plan-level feasibility is affected and the resolution escalates to
replanning (docs/06). Half-open semantics throughout: back-to-back
is not a conflict.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.schedule import Schedule
from backcasting.domain.timezone import require_utc


class ConflictResolutionError(ValueError):
    """Raised when a conflict-resolution invariant is violated."""


class ResolutionAction(str, Enum):
    """What happens to a displaced placement."""

    RESCHEDULE = "reschedule"
    ESCALATE_TO_REPLANNING = "escalate_to_replanning"


@dataclass(frozen=True)
class Displacement:
    """A placement that must vacate ``[blocked_start, blocked_end)``."""

    schedule: Schedule
    blocked_start: datetime
    blocked_end: datetime


@dataclass(frozen=True)
class ConflictResolution:
    """The decided action for a displaced placement."""

    action: ResolutionAction
    schedule: Schedule
    slots: tuple[CandidateSlot, ...]

    @property
    def reason(self) -> str:
        if self.action is ResolutionAction.ESCALATE_TO_REPLANNING:
            return "NO_AVAILABLE_SLOT: no candidate placement survives"
        return "reschedulable: candidates survive for re-placement"


def _validate_schedules(schedules) -> None:
    if not isinstance(schedules, tuple):
        raise ConflictResolutionError("schedules must be a tuple of Schedule")
    for schedule in schedules:
        if not isinstance(schedule, Schedule):
            raise ConflictResolutionError("schedules must be Schedule instances")


def _validate_events(events) -> None:
    if not isinstance(events, tuple):
        raise ConflictResolutionError("events must be a tuple of CalendarEvent")
    for event in events:
        if not isinstance(event, CalendarEvent):
            raise ConflictResolutionError("events must be CalendarEvent instances")


def displace_for_commitments(
    schedules: tuple[Schedule, ...],
    events: tuple[CalendarEvent, ...],
) -> tuple[Displacement, ...]:
    """Commitments outrank placements (docs/05): every schedule
    overlapping a calendar event is displaced.

    One :class:`Displacement` per overlapping (schedule, event) pair,
    in deterministic order — schedules swept by ``(start, end, id)``,
    events likewise.
    """
    _validate_schedules(schedules)
    _validate_events(events)

    displacements: list[Displacement] = []
    for schedule in sorted(schedules, key=lambda s: (s.start, s.end, s.schedule_id)):
        for event in sorted(events, key=lambda e: (e.start, e.end, e.event_id)):
            blocked_start = max(schedule.start, event.start)
            blocked_end = min(schedule.end, event.end)
            if blocked_start < blocked_end:
                displacements.append(
                    Displacement(
                        schedule=schedule,
                        blocked_start=blocked_start,
                        blocked_end=blocked_end,
                    )
                )
    return tuple(displacements)


def displace_between_placements(
    schedules: tuple[Schedule, ...],
) -> tuple[Displacement, ...]:
    """Resolve overlaps between placements: the later-starting one yields.

    Ties break by later end, then later schedule id — deterministic
    regardless of input order. Overlapping placements of the *same*
    task violate the placement invariant (one task cannot be in two
    places at once) and raise instead of resolving.
    """
    _validate_schedules(schedules)

    ordered = sorted(schedules, key=lambda s: (s.start, s.end, s.schedule_id))
    displacements: list[Displacement] = []
    for i, kept in enumerate(ordered):
        for yielded in ordered[i + 1 :]:
            if yielded.start >= kept.end:
                break  # later placements start even later
            if yielded.task_id == kept.task_id:
                raise ConflictResolutionError(
                    "a task's placements must not overlap (schedule.py invariant)"
                )
            displacements.append(
                Displacement(
                    schedule=yielded,
                    blocked_start=yielded.start,
                    blocked_end=min(kept.end, yielded.end),
                )
            )
    return tuple(displacements)


def resolve_displacement(
    schedule: Schedule,
    slots: tuple[CandidateSlot, ...],
) -> ConflictResolution:
    """Decide the action for a displaced placement (docs/06).

    ``slots`` are the displaced task's surviving candidates — already
    filtered through the hierarchy by the caller. Non-empty: the
    conflict resolves through rescheduling, and the slots are where
    the task re-places. Empty: no placement exists anywhere;
    Plan-level feasibility is affected — escalate to replanning.
    """
    if not isinstance(schedule, Schedule):
        raise ConflictResolutionError("schedule must be a Schedule")
    if not isinstance(slots, tuple):
        raise ConflictResolutionError("slots must be a tuple of CandidateSlot")
    for slot in slots:
        if not isinstance(slot, CandidateSlot):
            raise ConflictResolutionError("slots must be CandidateSlot instances")

    if slots:
        return ConflictResolution(
            action=ResolutionAction.RESCHEDULE, schedule=schedule, slots=slots
        )
    return ConflictResolution(
        action=ResolutionAction.ESCALATE_TO_REPLANNING,
        schedule=schedule,
        slots=(),
    )


def displacements_for_task(
    displacements: tuple[Displacement, ...],
    task_id: uuid.UUID,
) -> tuple[Displacement, ...]:
    """The displacements concerning one task's placements."""
    if not isinstance(task_id, uuid.UUID):
        raise ConflictResolutionError("task_id must be a UUID")
    _validate_displacements(displacements)
    return tuple(d for d in displacements if d.schedule.task_id == task_id)


def _validate_displacements(displacements) -> None:
    if not isinstance(displacements, tuple):
        raise ConflictResolutionError("displacements must be a tuple")
    for displacement in displacements:
        if not isinstance(displacement, Displacement):
            raise ConflictResolutionError(
                "displacements must be Displacement instances"
            )
        require_utc(
            "blocked_start", displacement.blocked_start, error=ConflictResolutionError
        )
        require_utc(
            "blocked_end", displacement.blocked_end, error=ConflictResolutionError
        )
