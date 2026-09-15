"""Tests for backcasting pipeline integration (TASK-028).

Pins the orchestration of the deterministic pipeline steps built in
EPIC-003 (gap → feasibility → strategies → selection → milestones) and
the failure semantics: the run is started before the first fallible
step, ends exactly once, and failures carry the FAILED run.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.backcasting import (
    BackcastingResult,
    BackcastingStepError,
    BackcastingPipelineError,
    InfeasibleBackcasting,
    execute_backcasting,
)
from backcasting.domain.backcasting_run import BackcastingRunStatus
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.goal import create_goal
from backcasting.domain.metric import Metric, MetricDirection, MetricKind
from backcasting.domain.milestone import MilestoneProposal
from backcasting.domain.strategy import StrategyProposal, StrategyStatus

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
EXECUTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)
CHECKPOINT_1 = datetime(2026, 3, 1, tzinfo=timezone.utc)
CHECKPOINT_2 = datetime(2026, 6, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def _distance_metric() -> Metric:
    return Metric(
        name="Longest run",
        kind=MetricKind.COUNT,
        direction=MetricDirection.MAXIMIZE,
    )


def _context():
    goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
    current = capture_current_state(
        goal.goal_id, "Can run 5 km.", captured_at=CAPTURED
    )
    future = define_future_state(
        goal.goal_id, "Complete the marathon.", TARGET, created_at=CREATED
    )
    return goal, current, future


def _strategy_proposals() -> tuple[StrategyProposal, ...]:
    return (
        StrategyProposal("Run more kilometers"),
        StrategyProposal("Add interval training"),
    )


def _milestone_proposals() -> tuple[MilestoneProposal, ...]:
    return (
        MilestoneProposal("10 km", CHECKPOINT_1),
        MilestoneProposal("Half-marathon", CHECKPOINT_2),
    )


def _execute(
    goal,
    current,
    future,
    *,
    workload=30 * HOUR,
    buffer=5 * HOUR,
    capacity=50 * HOUR,
    selected="Run more kilometers",
    strategies=None,
    milestones=None,
    run_id=None,
    at=EXECUTED,
):
    return execute_backcasting(
        goal,
        current,
        future,
        ((_distance_metric(), 5, 42),),
        required_workload=workload,
        buffer=buffer,
        usable_capacity=capacity,
        strategy_proposals=strategies
        if strategies is not None
        else _strategy_proposals(),
        selected_strategy_name=selected,
        milestone_proposals=milestones
        if milestones is not None
        else _milestone_proposals(),
        run_id=run_id,
        at=at,
    )


class TestExecuteBackcasting:
    def test_happy_path_produces_a_completed_result(self) -> None:
        goal, current, future = _context()
        result = _execute(goal, current, future)
        assert isinstance(result, BackcastingResult)
        assert result.run.status is BackcastingRunStatus.COMPLETED
        assert result.run.completed_at == EXECUTED
        assert result.run.goal_id == goal.goal_id
        assert result.run.current_state_id == current.state_id
        assert result.run.future_state_id == future.state_id
        assert result.run.gap_id == result.gap.gap_id

    def test_gap_is_calculated_from_the_measurements(self) -> None:
        goal, current, future = _context()
        result = _execute(goal, current, future)
        assert result.gap.goal_id == goal.goal_id
        dimension = result.gap.dimensions[0]
        assert dimension.metric.name == "Longest run"
        assert dimension.current_value == 5
        assert dimension.target_value == 42

    def test_feasibility_is_evaluated_and_exposed(self) -> None:
        goal, current, future = _context()
        result = _execute(goal, current, future)
        assert result.feasibility.feasible is True
        assert result.feasibility.slack == 15 * HOUR

    def test_named_strategy_is_selected_others_rejected(self) -> None:
        goal, current, future = _context()
        result = _execute(goal, current, future, selected="Add interval training")
        assert result.selected_strategy.name == "Add interval training"
        assert result.selected_strategy.status is StrategyStatus.SELECTED
        assert [s.name for s in result.rejected_strategies] == ["Run more kilometers"]
        assert all(
            s.status is StrategyStatus.REJECTED for s in result.rejected_strategies
        )

    def test_selection_name_is_matched_after_stripping(self) -> None:
        goal, current, future = _context()
        result = _execute(goal, current, future, selected="  Run more kilometers  ")
        assert result.selected_strategy.name == "Run more kilometers"

    def test_milestones_are_accepted_and_bound(self) -> None:
        goal, current, future = _context()
        result = _execute(goal, current, future)
        assert [m.title for m in result.milestones] == ["10 km", "Half-marathon"]
        for milestone in result.milestones:
            assert milestone.run_id == result.run.run_id
            assert milestone.goal_id == goal.goal_id
            assert milestone.created_at == EXECUTED

    def test_single_candidate_has_no_rejections(self) -> None:
        goal, current, future = _context()
        result = _execute(
            goal,
            current,
            future,
            strategies=(StrategyProposal("Only way"),),
            selected="Only way",
        )
        assert result.rejected_strategies == ()

    def test_injectable_run_id_and_clock(self) -> None:
        goal, current, future = _context()
        run_id = uuid.uuid4()
        result = _execute(goal, current, future, run_id=run_id)
        assert result.run.run_id == run_id
        assert result.run.started_at == EXECUTED
        assert result.selected_strategy.created_at == EXECUTED
        assert result.gap.calculated_at == EXECUTED


class TestFailureSemantics:
    def test_infeasible_plan_fails_the_run(self) -> None:
        goal, current, future = _context()
        with pytest.raises(InfeasibleBackcasting) as excinfo:
            _execute(goal, current, future, workload=60 * HOUR, capacity=50 * HOUR)
        failure = excinfo.value
        assert failure.run.status is BackcastingRunStatus.FAILED
        assert failure.run.completed_at == EXECUTED
        assert failure.feasibility.feasible is False
        assert failure.feasibility.slack == -15 * HOUR
        assert failure.feasibility.total_required == 65 * HOUR

    def test_invalid_strategy_batch_fails_the_run(self) -> None:
        goal, current, future = _context()
        with pytest.raises(BackcastingStepError) as excinfo:
            _execute(goal, current, future, strategies=())
        assert excinfo.value.step == "generate candidate strategies"
        assert excinfo.value.run.status is BackcastingRunStatus.FAILED
        assert excinfo.value.cause is not None

    def test_unknown_selection_fails_the_run(self) -> None:
        goal, current, future = _context()
        with pytest.raises(BackcastingStepError) as excinfo:
            _execute(goal, current, future, selected="Does not exist")
        assert excinfo.value.step == "select strategy"
        assert excinfo.value.run.status is BackcastingRunStatus.FAILED

    def test_invalid_milestone_batch_fails_the_run(self) -> None:
        goal, current, future = _context()
        with pytest.raises(BackcastingStepError) as excinfo:
            _execute(
                goal,
                current,
                future,
                milestones=(MilestoneProposal("Too late", TARGET),),
            )
        assert excinfo.value.step == "generate milestones"
        assert excinfo.value.run.status is BackcastingRunStatus.FAILED

    def test_step_error_preserves_the_cause(self) -> None:
        goal, current, future = _context()
        with pytest.raises(BackcastingStepError) as excinfo:
            _execute(goal, current, future, milestones=())
        assert isinstance(excinfo.value.cause, Exception)
        assert excinfo.value.__cause__ is excinfo.value.cause


class TestInputGuards:
    @pytest.mark.parametrize("name", ["", "   ", 42, None])
    def test_empty_or_non_string_selection_name_is_rejected_before_start(
        self, name: object
    ) -> None:
        goal, current, future = _context()
        with pytest.raises(BackcastingPipelineError):
            _execute(goal, current, future, selected=name)

    def test_invalid_context_is_rejected_before_start(self) -> None:
        goal, _, future = _context()
        foreign = capture_current_state(
            uuid.uuid4(), "Someone else's reality.", captured_at=CAPTURED
        )
        with pytest.raises(Exception):
            _execute(goal, foreign, future)
