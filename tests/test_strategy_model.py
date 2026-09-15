"""Tests for the Strategy domain model (TASK-023).

Covers the candidate lifecycle (CANDIDATE → SELECTED/REJECTED, one-shot),
entity invariants, the propose-during-running-run guard, and decide
transitions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.backcasting_run import (
    BackcastingRunStatus,
    complete_run,
    start_run,
)
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.metric import Metric, MetricDirection, MetricKind
from backcasting.domain.strategy import (
    MAX_NAME_LENGTH,
    MAX_RATIONALE_LENGTH,
    STRATEGY_TRANSITIONS,
    TERMINAL_STRATEGY_STATUSES,
    InvalidStrategyTransition,
    Strategy,
    StrategyError,
    StrategyStatus,
    decide_strategy,
    propose_strategy,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
CALCULATED = datetime(2026, 1, 6, tzinfo=timezone.utc)
STARTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
DECIDED = STARTED + timedelta(minutes=2)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)


@pytest.fixture
def running_run() -> BackcastingRun:
    goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
    current = capture_current_state(
        goal.goal_id, "Can run 5 km.", captured_at=CAPTURED
    )
    future = define_future_state(
        goal.goal_id, "Complete the marathon.", TARGET, created_at=CREATED
    )
    gap = calculate_gap(goal, current, future, calculated_at=CALCULATED)
    return start_run(goal, current, future, gap, started_at=STARTED)


class TestStrategyStatus:
    def test_statuses_match_pipeline(self) -> None:
        assert [s.value for s in StrategyStatus] == [
            "candidate",
            "selected",
            "rejected",
        ]

    def test_candidate_may_be_decided_either_way(self) -> None:
        assert STRATEGY_TRANSITIONS[StrategyStatus.CANDIDATE] == frozenset(
            {StrategyStatus.SELECTED, StrategyStatus.REJECTED}
        )

    @pytest.mark.parametrize("status", sorted(TERMINAL_STRATEGY_STATUSES))
    def test_terminal_statuses_are_final(self, status: StrategyStatus) -> None:
        assert STRATEGY_TRANSITIONS[status] == frozenset()


class TestStrategy:
    def _valid_kwargs(self, running_run) -> dict:
        return {
            "strategy_id": uuid.uuid4(),
            "run_id": running_run.run_id,
            "goal_id": running_run.goal_id,
            "name": "Base-first build-up",
            "rationale": "Aerobic base before volume.",
            "created_at": STARTED,
            "updated_at": STARTED,
        }

    def test_valid_strategy_round_trips(self, running_run) -> None:
        kwargs = self._valid_kwargs(running_run)
        strategy = Strategy(**kwargs)
        assert strategy.name == "Base-first build-up"
        assert strategy.rationale == "Aerobic base before volume."
        assert strategy.status is StrategyStatus.CANDIDATE

    def test_name_is_stripped_and_bounded(self, running_run) -> None:
        strategy = Strategy(
            **{**self._valid_kwargs(running_run), "name": "  Base first  "}
        )
        assert strategy.name == "Base first"
        with pytest.raises(StrategyError):
            Strategy(
                **{
                    **self._valid_kwargs(running_run),
                    "name": "x" * (MAX_NAME_LENGTH + 1),
                }
            )

    def test_strategy_is_immutable(self, running_run) -> None:
        strategy = Strategy(**self._valid_kwargs(running_run))
        with pytest.raises(AttributeError):
            strategy.name = "other"  # type: ignore[misc]

    @pytest.mark.parametrize("key", ["strategy_id", "run_id", "goal_id"])
    def test_non_uuid_references_are_rejected(self, running_run, key: str) -> None:
        with pytest.raises(StrategyError):
            Strategy(**{**self._valid_kwargs(running_run), key: "not-a-uuid"})

    def test_overlong_rationale_is_rejected(self, running_run) -> None:
        with pytest.raises(StrategyError):
            Strategy(
                **{
                    **self._valid_kwargs(running_run),
                    "rationale": "x" * (MAX_RATIONALE_LENGTH + 1),
                }
            )

    def test_naive_timestamps_are_rejected(self, running_run) -> None:
        with pytest.raises(StrategyError):
            Strategy(**{**self._valid_kwargs(running_run), "created_at": datetime(2026, 1, 6)})
        with pytest.raises(StrategyError):
            Strategy(**{**self._valid_kwargs(running_run), "updated_at": datetime(2026, 1, 6)})

    def test_non_utc_timestamps_are_rejected(self, running_run) -> None:
        # Europe/Berlin is UTC+1 on 2026-01-06.
        local = datetime(2026, 1, 6, 12, tzinfo=ZoneInfo("Europe/Berlin"))
        with pytest.raises(StrategyError):
            Strategy(**{**self._valid_kwargs(running_run), "created_at": local})

    def test_updated_before_created_is_rejected(self, running_run) -> None:
        with pytest.raises(StrategyError):
            Strategy(
                **{
                    **self._valid_kwargs(running_run),
                    "updated_at": STARTED - timedelta(seconds=1),
                }
            )

    def test_non_status_is_rejected(self, running_run) -> None:
        with pytest.raises(StrategyError):
            Strategy(**{**self._valid_kwargs(running_run), "status": "candidate"})


class TestProposeStrategy:
    def test_proposes_a_candidate(self, running_run) -> None:
        strategy = propose_strategy(
            running_run, "Base-first build-up", rationale="Aerobic base first.",
            created_at=STARTED,
        )
        assert strategy.status is StrategyStatus.CANDIDATE
        assert strategy.run_id == running_run.run_id
        assert strategy.goal_id == running_run.goal_id

    def test_generates_identity_and_timestamps(self, running_run) -> None:
        before = datetime.now(timezone.utc)
        strategy = propose_strategy(running_run, "Base-first build-up")
        after = datetime.now(timezone.utc)
        assert isinstance(strategy.strategy_id, uuid.UUID)
        assert before <= strategy.created_at <= after

    def test_injected_identity_is_honoured(self, running_run) -> None:
        strategy_id = uuid.uuid4()
        strategy = propose_strategy(
            running_run, "Base-first", strategy_id=strategy_id, created_at=STARTED
        )
        assert strategy.strategy_id == strategy_id

    def test_finished_run_refuses_proposals(self, running_run) -> None:
        finished = complete_run(running_run, completed_at=STARTED + timedelta(minutes=5))
        with pytest.raises(StrategyError):
            propose_strategy(finished, "Too late")

    def test_invalid_name_is_rejected(self, running_run) -> None:
        with pytest.raises(StrategyError):
            propose_strategy(running_run, "   ")

    def test_non_run_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            propose_strategy("run", "name")  # type: ignore[arg-type]


class TestDecideStrategy:
    def _candidate(self, running_run) -> Strategy:
        return propose_strategy(
            running_run, "Base-first build-up", created_at=STARTED
        )

    @pytest.mark.parametrize(
        "to_status",
        [StrategyStatus.SELECTED, StrategyStatus.REJECTED],
    )
    def test_candidate_can_be_decided(self, running_run, to_status) -> None:
        candidate = self._candidate(running_run)
        decided = decide_strategy(candidate, to_status, at=DECIDED)
        assert decided.status is to_status
        assert decided.updated_at == DECIDED
        assert decided.created_at == STARTED

    def test_decision_keeps_identity(self, running_run) -> None:
        candidate = self._candidate(running_run)
        decided = decide_strategy(candidate, StrategyStatus.SELECTED, at=DECIDED)
        assert decided.strategy_id == candidate.strategy_id
        assert decided.run_id == candidate.run_id
        assert candidate.status is StrategyStatus.CANDIDATE  # original untouched

    def test_same_status_is_illegal(self, running_run) -> None:
        with pytest.raises(InvalidStrategyTransition):
            decide_strategy(
                self._candidate(running_run), StrategyStatus.CANDIDATE, at=DECIDED
            )

    def test_terminal_strategy_cannot_move(self, running_run) -> None:
        selected = decide_strategy(
            self._candidate(running_run), StrategyStatus.SELECTED, at=DECIDED
        )
        with pytest.raises(InvalidStrategyTransition):
            decide_strategy(selected, StrategyStatus.REJECTED, at=DECIDED)
        with pytest.raises(InvalidStrategyTransition):
            decide_strategy(selected, StrategyStatus.CANDIDATE, at=DECIDED)

    def test_decision_defaults_to_now(self, running_run) -> None:
        before = datetime.now(timezone.utc)
        decided = decide_strategy(
            self._candidate(running_run), StrategyStatus.SELECTED
        )
        after = datetime.now(timezone.utc)
        assert before <= decided.updated_at <= after

    def test_non_status_target_is_rejected(self, running_run) -> None:
        with pytest.raises(StrategyError):
            decide_strategy(
                self._candidate(running_run), "selected", at=DECIDED  # type: ignore[arg-type]
            )

    def test_decision_timestamp_must_not_precede_creation(self, running_run) -> None:
        with pytest.raises(StrategyError):
            decide_strategy(
                self._candidate(running_run),
                StrategyStatus.SELECTED,
                at=STARTED - timedelta(seconds=1),
            )
