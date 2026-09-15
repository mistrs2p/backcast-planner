"""Deadline handling for candidate slots.

The deadline layer of the scheduling hierarchy (docs/05): a task
carrying a ``deadline`` (TASK-050) must *finish* by it. The rule as
slot arithmetic: a slot's usable part ends no later than the
deadline — slots are clipped, not destroyed — and a slot whose
pre-deadline remainder cannot hold the task's duration is dropped.
A task whose candidates all fall to that rule is the
``DEADLINE_CONFLICT`` failure reason (docs/06): the fact surfaces
upstream, here it is simply an empty list.

Half-open semantics: finishing exactly at the deadline is on time.
A task without a deadline has no deadline layer to apply — its
candidates pass through untouched.
"""

from __future__ import annotations

from datetime import timedelta

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.task import Task


class DeadlineFilterError(ValueError):
    """Raised when a deadline-filtering invariant is violated."""


def filter_slots_by_deadline(
    slots: tuple[CandidateSlot, ...],
    *,
    task: Task,
    duration: timedelta,
) -> tuple[CandidateSlot, ...]:
    """Clip ``slots`` to end no later than ``task``'s deadline.

    ``duration`` is the task's estimated duration (the placement must
    fit inside what survives the clip). Slots keep input order; only
    pieces at least ``duration`` long survive.
    """
    if not isinstance(slots, tuple):
        raise DeadlineFilterError("slots must be a tuple of CandidateSlot")
    for slot in slots:
        if not isinstance(slot, CandidateSlot):
            raise DeadlineFilterError("slots must be CandidateSlot instances")
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise DeadlineFilterError("duration must be a strictly positive timedelta")

    if task.deadline is None:
        return slots

    filtered: list[CandidateSlot] = []
    for slot in slots:
        end = min(slot.end, task.deadline)
        if end - slot.start >= duration:
            filtered.append(CandidateSlot(start=slot.start, end=end))
    return tuple(filtered)
