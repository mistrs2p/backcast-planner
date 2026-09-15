"""Hard constraint filtering of candidate slots.

The first layer of the scheduling hierarchy: "Hard constraints →
existing commitments → …" (docs/05). Constraints remove availability —
they narrow or destroy candidate slots, never create them — and
"Hard constraints are never violated" (docs/13), so the filter is
subtractive and absolute. A task that loses its last slot to a
constraint surfaces as the ``HARD_CONSTRAINT`` failure reason
(docs/06) upstream; here, the fact is simply a shorter (or empty)
slot list.

Semantics mirror the capacity chain's treatment of constraints
(:func:`analyze_time_environment` subtracts constraint blocks from
availability): each slot has every constraint's blocked intervals
subtracted from it — half-open, so a slot ending exactly as a block
begins is untouched — and the surviving pieces are kept only when
they can still hold the task's duration. Slots stay maximal within
what the constraints leave.
"""

from __future__ import annotations

from datetime import timedelta

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.constraint import Constraint, blocked_intervals
from backcasting.domain.planned_capacity import _merge, _subtract
from backcasting.domain.timezone import require_utc


class ConstraintFilterError(ValueError):
    """Raised when a constraint-filtering invariant is violated."""


def filter_slots_by_constraints(
    slots: tuple[CandidateSlot, ...],
    constraints: tuple[Constraint, ...],
    *,
    duration: timedelta,
) -> tuple[CandidateSlot, ...]:
    """Narrow ``slots`` by subtracting every constraint's blocks.

    Each slot keeps only the pieces that remain after all blocked
    intervals are removed and that are still at least ``duration``
    long. The result is chronological: slots are processed in order
    and pieces within a slot stay in order.
    """
    if not isinstance(slots, tuple):
        raise ConstraintFilterError("slots must be a tuple of CandidateSlot")
    for slot in slots:
        if not isinstance(slot, CandidateSlot):
            raise ConstraintFilterError("slots must be CandidateSlot instances")
    if not isinstance(constraints, tuple):
        raise ConstraintFilterError("constraints must be a tuple of Constraint")
    for constraint in constraints:
        if not isinstance(constraint, Constraint):
            raise ConstraintFilterError(
                "constraints must be Constraint instances"
            )
    if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise ConstraintFilterError("duration must be a strictly positive timedelta")

    filtered: list[CandidateSlot] = []
    for slot in slots:
        require_utc("slot start", slot.start, error=ConstraintFilterError)
        blocks: list[tuple] = []
        for constraint in constraints:
            blocks.extend(
                blocked_intervals(
                    constraint, range_start=slot.start, range_end=slot.end
                )
            )
        pieces = _subtract([(slot.start, slot.end)], _merge(blocks))
        for start, end in pieces:
            if end - start >= duration:
                filtered.append(CandidateSlot(start=start, end=end))
    return tuple(filtered)
