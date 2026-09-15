"""Task splitting across candidate slots.

The fallback of the placement step: when no single surviving
candidate slot can hold a task's full estimated duration, the work
is split across several. Slots arrive ranked (the preference layer,
TASK-062, orders best-first); splitting allocates the duration
greedily in that order — the best slot hosts as much as it can at
the planning granularity, the remainder flows to the next.

The planning granularity (docs/05: "Planning granularity is 15
minutes for MVP") is the quantum: every part is a whole multiple of
it and no smaller. A duration that is not itself a multiple is not
splittable — the estimate was made off-granularity and that fact
should surface as an error, not be silently re-rounded here.

Each slot hosts at most one part, packed from its start; the parts
sum to exactly the requested duration. When the slots cannot absorb
the whole duration the result is empty — the ``NO_AVAILABLE_SLOT``
fact (docs/06), surfaced upstream the way the filters surface
theirs, never routed around.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from backcasting.domain.candidate_slot import CandidateSlot

DEFAULT_GRANULARITY = timedelta(minutes=15)


class TaskSplittingError(ValueError):
    """Raised when a task-splitting invariant is violated."""


@dataclass(frozen=True)
class SlotAllocation:
    """One part of a split task: ``[start, end)`` inside ``slot``."""

    slot: CandidateSlot
    start: datetime
    end: datetime

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


def _floor_to(value: timedelta, granularity: timedelta) -> timedelta:
    whole = value // granularity
    return whole * granularity


def split_task_across_slots(
    slots: tuple[CandidateSlot, ...],
    *,
    duration: timedelta,
    granularity: timedelta = DEFAULT_GRANULARITY,
) -> tuple[SlotAllocation, ...]:
    """Split ``duration`` across ``slots`` in greedy (ranked) order.

    Returns the allocations — one per slot, at most, packed from the
    slot's start, each a positive multiple of ``granularity`` — or an
    empty tuple when the slots cannot absorb the whole duration.
    """
    if not isinstance(slots, tuple):
        raise TaskSplittingError("slots must be a tuple of CandidateSlot")
    for slot in slots:
        if not isinstance(slot, CandidateSlot):
            raise TaskSplittingError("slots must be CandidateSlot instances")
    if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise TaskSplittingError("duration must be a strictly positive timedelta")
    if not isinstance(granularity, timedelta) or granularity <= timedelta(0):
        raise TaskSplittingError("granularity must be a strictly positive timedelta")
    if duration % granularity != timedelta(0):
        raise TaskSplittingError(
            "duration must be a whole multiple of the planning granularity"
            f" ({granularity}); estimates are made on-granularity (docs/05)"
        )

    allocations: list[SlotAllocation] = []
    remaining = duration
    for slot in slots:
        if remaining <= timedelta(0):
            break
        capacity = _floor_to(slot.duration, granularity)
        take = min(remaining, capacity)
        if take < granularity:
            continue
        allocations.append(
            SlotAllocation(
                slot=slot, start=slot.start, end=slot.start + take
            )
        )
        remaining -= take
    if remaining > timedelta(0):
        return ()
    return tuple(allocations)
