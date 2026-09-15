"""Backcasting pipeline integration.

``execute_backcasting`` orchestrates the deterministic core of the
backcasting pipeline (``docs/04-BACKCASTING-MODEL.md``) over an
assembled goal context, wiring together the pieces built in EPIC-003:

- step 4 — calculate the gap (:func:`calculate_gap`);
- step 7 — evaluate feasibility (:func:`evaluate_feasibility`);
- steps 8–9 — accept proposed strategies and select one
  (:func:`accept_proposed_strategies`, :func:`decide_strategy`);
- step 10 — accept proposed milestones
  (:func:`accept_proposed_milestones`).

Steps 5–6 (analyze time environment, estimate workload) belong to the
calendar and capacity epics; their outputs — workload, buffer, and
usable capacity — arrive here as inputs. Steps 11–15 (outcomes, tasks,
scheduling, validation, publishing) belong to the planning epic and are
deliberately deferred: this integration ends with a COMPLETED run, the
selected strategy, and the milestone path.

Per ADR-002 the LLM-dependent steps arrive as *proposals*; this
orchestrator applies the deterministic rules and never generates
content itself.

Failure semantics: the run is started before the first fallible step
and ends exactly once. An infeasible plan fails the run and raises
:class:`InfeasibleBackcasting` carrying the FAILED run and the
feasibility numbers; any other step failure fails the run and raises
:class:`BackcastingStepError` carrying the FAILED run and the step
name. Callers can persist the carried run either way.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backcasting.domain.backcasting_run import (
    BackcastingRun,
    complete_run,
    fail_run,
    start_run,
)
from backcasting.domain.current_state import CurrentState
from backcasting.domain.feasibility import FeasibilityResult, evaluate_feasibility
from backcasting.domain.future_state import FutureState
from backcasting.domain.gap import Gap, calculate_gap
from backcasting.domain.goal import Goal
from backcasting.domain.milestone import (
    Milestone,
    MilestoneProposal,
    accept_proposed_milestones,
)
from backcasting.domain.metric import Metric
from backcasting.domain.strategy import (
    Strategy,
    StrategyProposal,
    StrategyStatus,
    accept_proposed_strategies,
    decide_strategy,
)


class BackcastingPipelineError(ValueError):
    """Raised when the backcasting pipeline cannot produce a plan."""


class InfeasibleBackcasting(BackcastingPipelineError):
    """Pipeline step 7 found the plan infeasible.

    Carries the FAILED run and the :class:`FeasibilityResult` so the
    caller can show *why* (slack) and persist the failed attempt.
    """

    def __init__(self, run: BackcastingRun, feasibility: FeasibilityResult) -> None:
        self.run = run
        self.feasibility = feasibility
        super().__init__(
            "backcasting failed: required workload + buffer exceeds usable capacity "
            f"(slack {feasibility.slack})"
        )


class BackcastingStepError(BackcastingPipelineError):
    """A pipeline step failed after the run started.

    Carries the FAILED run and the name of the failing step.
    """

    def __init__(self, run: BackcastingRun, step: str, cause: Exception) -> None:
        self.run = run
        self.step = step
        self.cause = cause
        super().__init__(f"backcasting step failed: {step}: {cause}")


@dataclass(frozen=True)
class BackcastingResult:
    """The outcome of one fully executed backcasting pipeline run."""

    run: BackcastingRun
    gap: Gap
    feasibility: FeasibilityResult
    selected_strategy: Strategy
    rejected_strategies: tuple[Strategy, ...]
    milestones: tuple[Milestone, ...]


def execute_backcasting(
    goal: Goal,
    current_state: CurrentState,
    future_state: FutureState,
    measurements: tuple[tuple[Metric, object, object], ...],
    *,
    required_workload: timedelta,
    buffer: timedelta,
    usable_capacity: timedelta,
    strategy_proposals: tuple[StrategyProposal, ...],
    selected_strategy_name: str,
    milestone_proposals: tuple[MilestoneProposal, ...],
    run_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> BackcastingResult:
    """Run the deterministic backcasting pipeline over a goal context.

    ``selected_strategy_name`` names the proposed strategy the pipeline
    selects (step 9); every other candidate is rejected. All steps share
    ``at`` (default: now) as their timestamp, so the whole execution is
    reproducible under an injected clock.
    """
    if not isinstance(selected_strategy_name, str) or not selected_strategy_name.strip():
        raise BackcastingPipelineError(
            "selected_strategy_name must be a non-empty string"
        )
    now = at if at is not None else datetime.now(timezone.utc)

    # Step 4 — calculate the gap for the assembled context.
    gap = calculate_gap(
        goal, current_state, future_state, measurements, calculated_at=now
    )
    run = start_run(
        goal, current_state, future_state, gap, run_id=run_id, started_at=now
    )

    def _step_error(step: str, cause: Exception) -> BackcastingStepError:
        return BackcastingStepError(fail_run(run, completed_at=now), step, cause)

    # Step 7 — feasibility (steps 5–6 are the caller-supplied inputs).
    feasibility = evaluate_feasibility(required_workload, buffer, usable_capacity)
    if not feasibility.feasible:
        raise InfeasibleBackcasting(fail_run(run, completed_at=now), feasibility)

    # Step 8 — accept the proposed candidate strategies.
    try:
        candidates = accept_proposed_strategies(run, strategy_proposals, at=now)
    except Exception as exc:
        raise _step_error("generate candidate strategies", exc) from exc

    # Step 9 — select the named candidate; reject the rest.
    wanted = selected_strategy_name.strip()
    selected_candidate = next(
        (candidate for candidate in candidates if candidate.name == wanted), None
    )
    if selected_candidate is None:
        raise _step_error(
            "select strategy",
            ValueError(f"no proposed strategy named {wanted!r}"),
        )
    selected_strategy = decide_strategy(
        selected_candidate, StrategyStatus.SELECTED, at=now
    )
    rejected_strategies = tuple(
        decide_strategy(candidate, StrategyStatus.REJECTED, at=now)
        for candidate in candidates
        if candidate.name != wanted
    )

    # Step 10 — accept the proposed milestone path.
    try:
        milestones = accept_proposed_milestones(
            run, future_state, milestone_proposals, at=now
        )
    except Exception as exc:
        raise _step_error("generate milestones", exc) from exc

    # The run records a pipeline execution; publishing the plan is the
    # planning epic's concern.
    return BackcastingResult(
        run=complete_run(run, completed_at=now),
        gap=gap,
        feasibility=feasibility,
        selected_strategy=selected_strategy,
        rejected_strategies=rejected_strategies,
        milestones=milestones,
    )
