"""Capacity filtering of candidate slots.

The capacity layer of the scheduling hierarchy (docs/05): before a
task's candidates are ranked, two capacity facts narrow them —
the goal's remaining budget, and the period the capacity was
analyzed over.

- **The budget gate.** A task consumes its ``duration`` from the
  goal's share of the capacity pool
  (:func:`CapacityPool.allocation_for`). When the remaining budget
  cannot hold the task, there is nothing to filter — the result is
  empty and the scheduler reports ``NO_CAPACITY`` (docs/06). This is
  the slot-level face of the feasibility rule the plan was already
  validated against: a feasible plan can still run out of pool share
  mid-execution when other goals consumed theirs.
- **The period window.** Usable capacity is analyzed over a period
  (:func:`analyze_time_environment`); slot time outside that period
  is not backed by any analysis, so slots are clipped to it and only
  the in-period pieces survive.

The filter never invents time and never silently shrinks a task: a
budget that fits the task keeps every in-period candidate — which
one hosts the task is the placement step's decision, informed by the
hierarchy's later layers.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.timezone import require_utc


class CapacityFilterError(ValueError):
    """Raised when a capacity-filtering invariant is violated."""


def filter_slots_by_capacity(
    slots: tuple[CandidateSlot, ...],
    *,
    period_start: datetime,
    period_end: datetime,
    budget: timedelta,
    duration: timedelta,
) -> tuple[CandidateSlot, ...]:
    """Filter ``slots`` by the goal's remaining capacity budget.

    Returns ``()`` when the budget cannot hold a task of ``duration``
    (the ``NO_CAPACITY`` fact); otherwise returns the slots clipped
    to ``[period_start, period_end)``, keeping only pieces at least
    ``duration`` long, in input order (generation is chronological).
    """
    if not isinstance(slots, tuple):
        raise CapacityFilterError("slots must be a tuple of CandidateSlot")
    for slot in slots:
        if not isinstance(slot, CandidateSlot):
            raise CapacityFilterError("slots must be CandidateSlot instances")
    require_utc("period_start", period_start, error=CapacityFilterError)
    require_utc("period_end", period_end, error=CapacityFilterError)
    if period_end <= period_start:
        raise CapacityFilterError("period_end must be after period_start")
    if not isinstance(budget, timedelta) or budget < timedelta(0):
        raise CapacityFilterError("budget must be a non-negative timedelta")
    if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise CapacityFilterError("duration must be a strictly positive timedelta")

    if budget < duration:
        return ()

    filtered: list[CandidateSlot] = []
    for slot in slots:
        start = max(slot.start, period_start)
        end = min(slot.end, period_end)
        if start < end and end - start >= duration:
            filtered.append(CandidateSlot(start=start, end=end))
    return tuple(filtered)
