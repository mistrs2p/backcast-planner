"""Feasibility engine.

Pipeline step 7, "Evaluate feasibility" (``docs/04-BACKCASTING-MODEL.md``),
applies the spec's feasibility rule::

    Required Workload + Buffer ≤ usable Capacity

This is a deterministic calculation (ADR-002: the domain is authoritative
for feasibility) over durations, not calendar placement — where the
capacity comes from and how it is spread over time are the calendar and
capacity concerns. Here we only compare the totals.

Rules:

- ``required_workload``, ``buffer``, and ``usable_capacity`` are
  non-negative :class:`~datetime.timedelta` values.
- A plan is feasible when ``required_workload + buffer ≤ usable_capacity``;
  the slack is ``usable_capacity - (required_workload + buffer)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


class FeasibilityError(ValueError):
    """Raised when a feasibility invariant is violated."""


def _require_duration(name: str, value: object) -> timedelta:
    if not isinstance(value, timedelta):
        raise FeasibilityError(
            f"{name} must be a timedelta, got {type(value).__name__}"
        )
    if value < timedelta(0):
        raise FeasibilityError(f"{name} must be non-negative, got {value}")
    return value


@dataclass(frozen=True)
class FeasibilityResult:
    """The outcome of the feasibility rule, with the arithmetic exposed.

    ``feasible`` applies the spec rule; ``slack`` is the remaining capacity
    (negative when infeasible) — the distance to the feasibility boundary.
    """

    required_workload: timedelta
    buffer: timedelta
    usable_capacity: timedelta
    feasible: bool
    total_required: timedelta
    slack: timedelta


def evaluate_feasibility(
    required_workload: timedelta,
    buffer: timedelta,
    usable_capacity: timedelta,
) -> FeasibilityResult:
    """Apply "Required Workload + Buffer ≤ usable Capacity" (docs/04)."""
    required_workload = _require_duration("required_workload", required_workload)
    buffer = _require_duration("buffer", buffer)
    usable_capacity = _require_duration("usable_capacity", usable_capacity)
    total_required = required_workload + buffer
    slack = usable_capacity - total_required
    return FeasibilityResult(
        required_workload=required_workload,
        buffer=buffer,
        usable_capacity=usable_capacity,
        feasible=slack >= timedelta(0),
        total_required=total_required,
        slack=slack,
    )
