"""Tests for strategy generation acceptance (TASK-024).

The domain does not generate strategies — the LLM does (docs/09 /
ADR-002). These tests cover the deterministic guard: proposals become run
candidates only when the run is RUNNING, the batch is non-empty, names are
unique, and every proposal is valid.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.backcasting_run import complete_run, start_run
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.strategy import (
    MAX_NAME_LENGTH,
    Strategy,
    StrategyError,
    StrategyProposal,
    StrategyStatus,
    accept_proposed_strategies,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
CALCULATED = datetime(2026, 1, 6, tzinfo=timezone.utc)
STARTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
PROPOSED_AT = STARTED + timedelta(minutes=1)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)


@pytest.fixture
def running_run():
    goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
    current = capture_current_state(
        goal.goal_id, "Can run 5 km.", captured_at=CAPTURED
    )
    future = define_future_state(
        goal.goal_id, "Complete the marathon.", TARGET, created_at=CREATED
    )
    gap = calculate_gap(goal, current, future, calculated_at=CALCULATED)
    return start_run(goal, current, future, gap, started_at=STARTED)


class TestStrategyProposal:
    def test_valid_proposal_round_trips(self) -> None:
        proposal = StrategyProposal("Base-first build-up", "Aerobic base first.")
        assert proposal.name == "Base-first build-up"
        assert proposal.rationale == "Aerobic base first."

    def test_name_is_stripped(self) -> None:
        assert StrategyProposal("  Base first  ").name == "Base first"

    def test_empty_name_is_rejected(self) -> None:
        with pytest.raises(StrategyError):
            StrategyProposal("   ")

    def test_overlong_name_is_rejected(self) -> None:
        with pytest.raises(StrategyError):
            StrategyProposal("x" * (MAX_NAME_LENGTH + 1))

    def test_rationale_is_optional(self) -> None:
        assert StrategyProposal("Name").rationale == ""

    def test_non_string_rationale_is_rejected(self) -> None:
        with pytest.raises(StrategyError):
            StrategyProposal("Name", rationale=5)  # type: ignore[arg-type]


class TestAcceptProposedStrategies:
    def test_proposals_become_candidates_in_order(self, running_run) -> None:
        candidates = accept_proposed_strategies(
            running_run,
            (
                StrategyProposal("Base-first build-up", "Aerobic base first."),
                StrategyProposal("Race-pace focus", "Speed early."),
            ),
            at=PROPOSED_AT,
        )
        assert len(candidates) == 2
        assert [c.name for c in candidates] == [
            "Base-first build-up",
            "Race-pace focus",
        ]
        assert all(c.status is StrategyStatus.CANDIDATE for c in candidates)
        assert all(c.run_id == running_run.run_id for c in candidates)
        assert all(c.goal_id == running_run.goal_id for c in candidates)
        assert all(c.created_at == PROPOSED_AT for c in candidates)
        assert all(isinstance(c, Strategy) for c in candidates)

    def test_single_proposal_is_accepted(self, running_run) -> None:
        candidates = accept_proposed_strategies(
            running_run, (StrategyProposal("Only path"),), at=PROPOSED_AT
        )
        assert len(candidates) == 1

    def test_empty_batch_is_rejected(self, running_run) -> None:
        with pytest.raises(StrategyError):
            accept_proposed_strategies(running_run, (), at=PROPOSED_AT)

    def test_duplicate_names_are_rejected(self, running_run) -> None:
        with pytest.raises(StrategyError):
            accept_proposed_strategies(
                running_run,
                (
                    StrategyProposal("Same name"),
                    StrategyProposal("Same name", "different rationale"),
                ),
                at=PROPOSED_AT,
            )

    def test_finished_run_refuses_proposals(self, running_run) -> None:
        finished = complete_run(
            running_run, completed_at=STARTED + timedelta(minutes=5)
        )
        with pytest.raises(StrategyError):
            accept_proposed_strategies(
                finished, (StrategyProposal("Too late"),), at=PROPOSED_AT
            )

    def test_non_tuple_batch_is_rejected(self, running_run) -> None:
        with pytest.raises(StrategyError):
            accept_proposed_strategies(
                running_run, [StrategyProposal("Name")], at=PROPOSED_AT  # type: ignore[arg-type]
            )

    def test_non_proposal_members_are_rejected(self, running_run) -> None:
        with pytest.raises(StrategyError):
            accept_proposed_strategies(
                running_run, ("name", "rationale"), at=PROPOSED_AT  # type: ignore[arg-type]
            )

    def test_non_run_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            accept_proposed_strategies(
                "run", (StrategyProposal("Name"),), at=PROPOSED_AT  # type: ignore[arg-type]
            )

    def test_candidates_are_distinct_instances(self, running_run) -> None:
        candidates = accept_proposed_strategies(
            running_run,
            (StrategyProposal("A"), StrategyProposal("B")),
            at=PROPOSED_AT,
        )
        assert candidates[0].strategy_id != candidates[1].strategy_id

    def test_timestamp_defaults_to_now(self, running_run) -> None:
        before = datetime.now(timezone.utc)
        candidates = accept_proposed_strategies(
            running_run, (StrategyProposal("A"),)
        )
        after = datetime.now(timezone.utc)
        assert before <= candidates[0].created_at <= after
