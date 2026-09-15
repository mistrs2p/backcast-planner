"""Tests for milestone generation (TASK-027).

Pins the deterministic side of pipeline step 10 (docs/04) per ADR-002:
the domain accepts AI-proposed milestone batches only when the run is
RUNNING against the exact destination, the batch is non-empty with
unique titles, and the checkpoints are strictly increasing and strictly
between acceptance and the destination's target date.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.backcasting_run import (
    BackcastingRun,
    BackcastingRunStatus,
    fail_run,
    start_run,
)
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.metric import Metric, MetricDirection, MetricKind
from backcasting.domain.milestone import (
    MilestoneError,
    MilestoneProposal,
    accept_proposed_milestones,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
CALCULATED = datetime(2026, 1, 6, tzinfo=timezone.utc)
STARTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
ACCEPTED = STARTED + timedelta(minutes=10)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)

CHECKPOINT_1 = datetime(2026, 3, 1, tzinfo=timezone.utc)
CHECKPOINT_2 = datetime(2026, 6, 1, tzinfo=timezone.utc)
CHECKPOINT_3 = datetime(2026, 9, 1, tzinfo=timezone.utc)


class Context:
    """Assembled goal context: goal, states, gap, and a RUNNING run."""

    def __init__(self) -> None:
        self.goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
        self.current = capture_current_state(
            self.goal.goal_id, "Can run 5 km.", captured_at=CAPTURED
        )
        self.future = define_future_state(
            self.goal.goal_id, "Complete the marathon.", TARGET, created_at=CREATED
        )
        self.gap = calculate_gap(self.goal, self.current, self.future, calculated_at=CALCULATED)
        self.run = start_run(
            self.goal, self.current, self.future, self.gap, started_at=STARTED
        )


@pytest.fixture
def context() -> Context:
    return Context()


def _proposals(*targets: datetime) -> tuple[MilestoneProposal, ...]:
    return tuple(
        MilestoneProposal(f"Checkpoint {index}", target)
        for index, target in enumerate(targets, start=1)
    )


class TestMilestoneProposal:
    def test_valid_proposal_is_accepted(self) -> None:
        proposal = MilestoneProposal("Half-marathon", CHECKPOINT_1, "21 km")
        assert proposal.title == "Half-marathon"
        assert proposal.target_date == CHECKPOINT_1
        assert proposal.description == "21 km"

    def test_title_is_stripped_and_bounded(self) -> None:
        assert MilestoneProposal("  Half  ", CHECKPOINT_1).title == "Half"
        with pytest.raises(MilestoneError):
            MilestoneProposal("x" * 201, CHECKPOINT_1)

    @pytest.mark.parametrize("title", ["", "   "])
    def test_empty_title_is_rejected(self, title: str) -> None:
        with pytest.raises(MilestoneError):
            MilestoneProposal(title, CHECKPOINT_1)

    def test_naive_target_date_is_rejected(self) -> None:
        with pytest.raises(MilestoneError):
            MilestoneProposal("Half-marathon", datetime(2026, 3, 1))

    def test_non_utc_target_date_is_rejected(self) -> None:
        with pytest.raises(MilestoneError):
            MilestoneProposal(
                "Half-marathon", CHECKPOINT_1.astimezone(ZoneInfo("Europe/Berlin"))
            )

    def test_description_is_optional_and_bounded(self) -> None:
        assert MilestoneProposal("Half", CHECKPOINT_1).description == ""
        with pytest.raises(MilestoneError):
            MilestoneProposal("Half", CHECKPOINT_1, "x" * 5001)

    def test_proposal_is_immutable(self) -> None:
        proposal = MilestoneProposal("Half", CHECKPOINT_1)
        with pytest.raises(AttributeError):
            proposal.title = "Other"  # type: ignore[misc]


class TestAcceptProposedMilestones:
    def test_accepts_ordered_checkpoints(self, context: Context) -> None:
        milestones = accept_proposed_milestones(
            context.run,
            context.future,
            _proposals(CHECKPOINT_1, CHECKPOINT_2, CHECKPOINT_3),
            at=ACCEPTED,
        )
        assert len(milestones) == 3
        assert [m.title for m in milestones] == [
            "Checkpoint 1",
            "Checkpoint 2",
            "Checkpoint 3",
        ]
        assert [m.target_date for m in milestones] == [
            CHECKPOINT_1,
            CHECKPOINT_2,
            CHECKPOINT_3,
        ]
        for milestone in milestones:
            assert milestone.run_id == context.run.run_id
            assert milestone.goal_id == context.goal.goal_id
            assert milestone.created_at == ACCEPTED

    def test_single_milestone_is_sufficient(self, context: Context) -> None:
        milestones = accept_proposed_milestones(
            context.run, context.future, _proposals(CHECKPOINT_1), at=ACCEPTED
        )
        assert len(milestones) == 1

    def test_empty_batch_is_rejected(self, context: Context) -> None:
        with pytest.raises(MilestoneError):
            accept_proposed_milestones(
                context.run, context.future, (), at=ACCEPTED
            )

    def test_non_tuple_batch_is_rejected(self, context: Context) -> None:
        with pytest.raises(MilestoneError):
            accept_proposed_milestones(
                context.run,
                context.future,
                [MilestoneProposal("Half", CHECKPOINT_1)],  # type: ignore[arg-type]
                at=ACCEPTED,
            )

    def test_non_proposal_elements_are_rejected(self, context: Context) -> None:
        with pytest.raises(MilestoneError):
            accept_proposed_milestones(
                context.run,
                context.future,
                ("Half",),  # type: ignore[arg-type]
                at=ACCEPTED,
            )

    def test_duplicate_titles_are_rejected(self, context: Context) -> None:
        proposals = (
            MilestoneProposal("Half-marathon", CHECKPOINT_1),
            MilestoneProposal("Half-marathon", CHECKPOINT_2),
        )
        with pytest.raises(MilestoneError, match="duplicate"):
            accept_proposed_milestones(
                context.run, context.future, proposals, at=ACCEPTED
            )

    def test_equal_target_dates_are_rejected(self, context: Context) -> None:
        proposals = (
            MilestoneProposal("Checkpoint 1", CHECKPOINT_1),
            MilestoneProposal("Checkpoint 2", CHECKPOINT_1),
        )
        with pytest.raises(MilestoneError, match="strictly increasing"):
            accept_proposed_milestones(
                context.run, context.future, proposals, at=ACCEPTED
            )

    def test_decreasing_target_dates_are_rejected(self, context: Context) -> None:
        proposals = (
            MilestoneProposal("Checkpoint 1", CHECKPOINT_2),
            MilestoneProposal("Checkpoint 2", CHECKPOINT_1),
        )
        with pytest.raises(MilestoneError, match="strictly increasing"):
            accept_proposed_milestones(
                context.run, context.future, proposals, at=ACCEPTED
            )

    def test_destination_target_date_is_rejected(self, context: Context) -> None:
        with pytest.raises(MilestoneError, match="precede"):
            accept_proposed_milestones(
                context.run, context.future, _proposals(TARGET), at=ACCEPTED
            )

    def test_target_date_after_destination_is_rejected(
        self, context: Context
    ) -> None:
        with pytest.raises(MilestoneError, match="precede"):
            accept_proposed_milestones(
                context.run, context.future, _proposals(TARGET + timedelta(days=1)), at=ACCEPTED
            )

    def test_target_date_at_or_before_acceptance_is_rejected(
        self, context: Context
    ) -> None:
        with pytest.raises(MilestoneError):
            accept_proposed_milestones(
                context.run, context.future, _proposals(ACCEPTED), at=ACCEPTED
            )

    def test_terminal_run_is_rejected(self, context: Context) -> None:
        failed = fail_run(context.run, completed_at=ACCEPTED)
        assert failed.status is BackcastingRunStatus.FAILED
        with pytest.raises(MilestoneError, match="status"):
            accept_proposed_milestones(
                failed, context.future, _proposals(CHECKPOINT_1), at=ACCEPTED
            )

    def test_foreign_future_state_is_rejected(self, context: Context) -> None:
        other_future = define_future_state(
            context.goal.goal_id,
            "A different destination.",
            TARGET + timedelta(days=30),
            created_at=CREATED,
        )
        with pytest.raises(MilestoneError, match="destination"):
            accept_proposed_milestones(
                context.run, other_future, _proposals(CHECKPOINT_1), at=ACCEPTED
            )

    def test_foreign_goal_future_state_is_rejected(self, context: Context) -> None:
        other_goal = create_goal(uuid.uuid4(), "Other goal", created_at=CREATED)
        other_future = define_future_state(
            other_goal.goal_id, "Other destination.", TARGET, created_at=CREATED
        )
        with pytest.raises(MilestoneError):
            accept_proposed_milestones(
                context.run, other_future, _proposals(CHECKPOINT_1), at=ACCEPTED
            )

    def test_non_run_is_rejected(self, context: Context) -> None:
        with pytest.raises(TypeError):
            accept_proposed_milestones(
                "not a run",  # type: ignore[arg-type]
                context.future,
                _proposals(CHECKPOINT_1),
                at=ACCEPTED,
            )

    def test_non_future_state_is_rejected(self, context: Context) -> None:
        with pytest.raises(TypeError):
            accept_proposed_milestones(
                context.run,
                "not a future state",  # type: ignore[arg-type]
                _proposals(CHECKPOINT_1),
                at=ACCEPTED,
            )
