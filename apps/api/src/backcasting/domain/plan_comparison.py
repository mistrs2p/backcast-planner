"""Plan comparison — current vs candidate, mechanically.

When replanning offers a candidate (a re-derived plan value from
the local, regional, or global scope), someone must say whether to
adopt it. Per ADR-002 the judgement dimensions the Domain owns are
the mechanical ones, and they are already fixed by the spec's own
rules:

- Feasibility (docs/04: "Required Workload + Buffer ≤ usable
  Capacity") is authoritative: a feasible plan beats an infeasible
  one, whatever else differs.
- With the Goal/Future fixed (level 2 — every replan preserves
  them), the candidate that needs less of the same capacity is the
  better plan: same destination, cheaper path. Both sides are
  judged under the *same* buffer and capacity, so the comparison
  is honest.
- A candidate that gains nothing — same feasibility verdict, same
  slack — is not adopted: the current plan stands, per docs/08's
  minimum-change principle.

The comparison states the arithmetic (both feasibility results,
the workload delta) alongside the verdict, so the reasoning layer
can see *why* and disagree with grounds rather than guesswork.
What it deliberately does not do: weigh anything the domain cannot
measure mechanically — strategic fit, preference, risk appetite.
Those belong to the LLM's reasoning and the user's judgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from backcasting.domain.feasibility import FeasibilityResult, evaluate_feasibility
from backcasting.domain.plan import Plan


class PlanComparisonError(ValueError):
    """Raised when a plan-comparison invariant is violated."""


class PreferredPlan(str, Enum):
    """Which plan the comparison favors."""

    CURRENT = "current"
    CANDIDATE = "candidate"


@dataclass(frozen=True)
class PlanComparison:
    """One current-vs-candidate verdict, with the arithmetic exposed."""

    current: Plan
    candidate: Plan
    current_feasibility: FeasibilityResult
    candidate_feasibility: FeasibilityResult
    workload_delta: timedelta  # candidate minus current
    preferred: PreferredPlan
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.current, Plan):
            raise PlanComparisonError("current must be a Plan")
        if not isinstance(self.candidate, Plan):
            raise PlanComparisonError("candidate must be a Plan")
        if self.candidate.plan_id != self.current.plan_id:
            raise PlanComparisonError(
                "candidate must be another version of the same plan"
            )
        if not isinstance(self.current_feasibility, FeasibilityResult):
            raise PlanComparisonError(
                "current_feasibility must be a FeasibilityResult"
            )
        if not isinstance(self.candidate_feasibility, FeasibilityResult):
            raise PlanComparisonError(
                "candidate_feasibility must be a FeasibilityResult"
            )
        if not isinstance(self.workload_delta, timedelta):
            raise PlanComparisonError("workload_delta must be a timedelta")
        if not isinstance(self.preferred, PreferredPlan):
            raise PlanComparisonError("preferred must be a PreferredPlan")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise PlanComparisonError("reason must be a non-empty string")


def compare_plans(
    current: Plan,
    candidate: Plan,
    *,
    buffer: timedelta,
    usable_capacity: timedelta,
) -> PlanComparison:
    """Compare a replan candidate against the current plan, both
    under the same buffer and capacity.

    Feasibility first (docs/04's rule is authoritative); then, with
    the verdicts equal, the candidate wins only on strictly more
    slack — a tie keeps the current plan (minimum-change).
    """
    if not isinstance(current, Plan):
        raise PlanComparisonError("current must be a Plan")
    if not isinstance(candidate, Plan):
        raise PlanComparisonError("candidate must be a Plan")
    if candidate.plan_id != current.plan_id:
        raise PlanComparisonError(
            "candidate must be another version of the same plan"
        )

    current_feasibility = evaluate_feasibility(
        current.workload, buffer, usable_capacity
    )
    candidate_feasibility = evaluate_feasibility(
        candidate.workload, buffer, usable_capacity
    )

    if current_feasibility.feasible and not candidate_feasibility.feasible:
        preferred, reason = PreferredPlan.CURRENT, "candidate-infeasible"
    elif candidate_feasibility.feasible and not current_feasibility.feasible:
        preferred, reason = PreferredPlan.CANDIDATE, "current-infeasible"
    elif candidate_feasibility.slack > current_feasibility.slack:
        preferred, reason = PreferredPlan.CANDIDATE, "more-slack"
    else:
        # Equal or less slack, verdicts equal: the current plan
        # stands — adopting a no-gain candidate is change for its
        # own sake (minimum-change principle).
        preferred, reason = PreferredPlan.CURRENT, "no-gain"

    return PlanComparison(
        current=current,
        candidate=candidate,
        current_feasibility=current_feasibility,
        candidate_feasibility=candidate_feasibility,
        workload_delta=candidate.workload - current.workload,
        preferred=preferred,
        reason=reason,
    )
