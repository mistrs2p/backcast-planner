"""Tests for the Backcasting run domain model (TASK-022).

Covers the run record's invariants (input references, UTC timestamps,
terminal-status/completed_at coupling), the start_run guards (validated
context, gap provenance), and the one-shot finish transitions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.backcasting_run import (
    BackcastingRun,
    BackcastingRunError,
    BackcastingRunStatus,
    complete_run,
    fail_run,
    start_run,
)
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.metric import Metric, MetricDirection, MetricKind
from backcasting.domain.validation import DomainValidationError

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
CALCULATED = datetime(2026, 1, 6, tzinfo=timezone.utc)
STARTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
FINISHED = STARTED + timedelta(minutes=5)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)

DISTANCE = Metric("Distance", MetricKind.COUNT, MetricDirection.MAXIMIZE)


@pytest.fixture
def context():
    goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
    current = capture_current_state(
        goal.goal_id, "Can run 5 km.", captured_at=CAPTURED
    )
    future = define_future_state(
        goal.goal_id, "Complete the marathon.", TARGET, created_at=CREATED
    )
    gap = calculate_gap(
        goal,
        current,
        future,
        ((DISTANCE, 5, 42),),
        calculated_at=CALCULATED,
    )
    return goal, current, future, gap


class TestBackcastingRun:
    def _valid_kwargs(self, context) -> dict:
        goal, current, future, gap = context
        return {
            "run_id": uuid.uuid4(),
            "goal_id": goal.goal_id,
            "current_state_id": current.state_id,
            "future_state_id": future.state_id,
            "gap_id": gap.gap_id,
            "started_at": STARTED,
        }

    def test_running_run_round_trips(self, context) -> None:
        kwargs = self._valid_kwargs(context)
        run = BackcastingRun(**kwargs)
        assert run.status is BackcastingRunStatus.RUNNING
        assert run.completed_at is None
        assert run.goal_id == kwargs["goal_id"]

    def test_run_is_immutable(self, context) -> None:
        run = BackcastingRun(**self._valid_kwargs(context))
        with pytest.raises(AttributeError):
            run.status = BackcastingRunStatus.COMPLETED  # type: ignore[misc]

    @pytest.mark.parametrize(
        "key",
        ["run_id", "goal_id", "current_state_id", "future_state_id", "gap_id"],
    )
    def test_non_uuid_references_are_rejected(self, context, key: str) -> None:
        with pytest.raises(BackcastingRunError):
            BackcastingRun(**{**self._valid_kwargs(context), key: "not-a-uuid"})

    def test_naive_started_at_is_rejected(self, context) -> None:
        with pytest.raises(BackcastingRunError):
            BackcastingRun(
                **{**self._valid_kwargs(context), "started_at": datetime(2026, 1, 6)}
            )

    def test_non_utc_started_at_is_rejected(self, context) -> None:
        # Europe/Berlin is UTC+1 on 2026-01-06.
        local = datetime(2026, 1, 6, 12, tzinfo=ZoneInfo("Europe/Berlin"))
        with pytest.raises(BackcastingRunError):
            BackcastingRun(**{**self._valid_kwargs(context), "started_at": local})

    def test_completed_run_is_valid(self, context) -> None:
        run = BackcastingRun(
            **{
                **self._valid_kwargs(context),
                "status": BackcastingRunStatus.COMPLETED,
                "completed_at": FINISHED,
            }
        )
        assert run.completed_at == FINISHED

    def test_running_run_cannot_carry_completed_at(self, context) -> None:
        with pytest.raises(BackcastingRunError):
            BackcastingRun(
                **{**self._valid_kwargs(context), "completed_at": FINISHED}
            )

    def test_terminal_run_requires_completed_at(self, context) -> None:
        with pytest.raises(BackcastingRunError):
            BackcastingRun(
                **{
                    **self._valid_kwargs(context),
                    "status": BackcastingRunStatus.FAILED,
                }
            )

    def test_completed_before_started_is_rejected(self, context) -> None:
        with pytest.raises(BackcastingRunError):
            BackcastingRun(
                **{
                    **self._valid_kwargs(context),
                    "status": BackcastingRunStatus.COMPLETED,
                    "completed_at": STARTED - timedelta(seconds=1),
                }
            )

    def test_naive_completed_at_is_rejected(self, context) -> None:
        with pytest.raises(BackcastingRunError):
            BackcastingRun(
                **{
                    **self._valid_kwargs(context),
                    "status": BackcastingRunStatus.COMPLETED,
                    "completed_at": datetime(2026, 1, 6, 13),
                }
            )


class TestStartRun:
    def test_starts_a_running_run(self, context) -> None:
        goal, current, future, gap = context
        run = start_run(goal, current, future, gap, started_at=STARTED)
        assert run.status is BackcastingRunStatus.RUNNING
        assert run.goal_id == goal.goal_id
        assert run.current_state_id == current.state_id
        assert run.future_state_id == future.state_id
        assert run.gap_id == gap.gap_id
        assert run.started_at == STARTED

    def test_generates_identity_and_timestamp(self, context) -> None:
        goal, current, future, gap = context
        before = datetime.now(timezone.utc)
        run = start_run(goal, current, future, gap)
        after = datetime.now(timezone.utc)
        assert isinstance(run.run_id, uuid.UUID)
        assert before <= run.started_at <= after

    def test_injected_identity_is_honoured(self, context) -> None:
        goal, current, future, gap = context
        run_id = uuid.uuid4()
        run = start_run(goal, current, future, gap, run_id=run_id, started_at=STARTED)
        assert run.run_id == run_id

    def test_mismatched_context_is_refused(self, context) -> None:
        goal, current, _, gap = context
        other_future = define_future_state(
            uuid.uuid4(), "Other goal.", TARGET, created_at=CREATED
        )
        with pytest.raises(DomainValidationError):
            start_run(goal, current, other_future, gap, started_at=STARTED)

    def test_gap_from_other_goal_is_refused(self, context) -> None:
        goal, current, future, _ = context
        other_goal = create_goal(uuid.uuid4(), "Other", created_at=CREATED)
        other_current = capture_current_state(
            other_goal.goal_id, "Other reality.", captured_at=CAPTURED
        )
        other_future = define_future_state(
            other_goal.goal_id, "Other destination.", TARGET, created_at=CREATED
        )
        other_gap = calculate_gap(
            other_goal, other_current, other_future, calculated_at=CALCULATED
        )
        with pytest.raises(BackcastingRunError):
            start_run(goal, current, future, other_gap, started_at=STARTED)

    def test_gap_from_other_snapshot_is_refused(self, context) -> None:
        goal, current, future, _ = context
        other_current = capture_current_state(
            goal.goal_id, "Later reality.", captured_at=CAPTURED + timedelta(days=1)
        )
        other_gap = calculate_gap(
            goal, other_current, future, calculated_at=CALCULATED
        )
        with pytest.raises(BackcastingRunError):
            start_run(goal, current, future, other_gap, started_at=STARTED)

    def test_gap_from_other_destination_is_refused(self, context) -> None:
        goal, current, future, _ = context
        other_future = define_future_state(
            goal.goal_id, "Other destination.", TARGET + timedelta(days=7),
            created_at=CREATED,
        )
        other_gap = calculate_gap(
            goal, current, other_future, calculated_at=CALCULATED
        )
        with pytest.raises(BackcastingRunError):
            start_run(goal, current, future, other_gap, started_at=STARTED)

    @pytest.mark.parametrize(
        "make_bad",
        [
            lambda g, c, f, gap: start_run("goal", c, f, gap),  # type: ignore[arg-type]
            lambda g, c, f, gap: start_run(g, "current", f, gap),  # type: ignore[arg-type]
            lambda g, c, f, gap: start_run(g, c, "future", gap),  # type: ignore[arg-type]
            lambda g, c, f, gap: start_run(g, c, f, "gap"),  # type: ignore[arg-type]
        ],
    )
    def test_wrong_types_raise_type_error(self, context, make_bad) -> None:
        with pytest.raises(TypeError):
            make_bad(*context)


class TestFinishRun:
    def test_complete_run(self, context) -> None:
        goal, current, future, gap = context
        run = start_run(goal, current, future, gap, started_at=STARTED)
        finished = complete_run(run, completed_at=FINISHED)
        assert finished.status is BackcastingRunStatus.COMPLETED
        assert finished.completed_at == FINISHED
        assert finished.run_id == run.run_id
        assert run.status is BackcastingRunStatus.RUNNING  # original untouched

    def test_fail_run(self, context) -> None:
        goal, current, future, gap = context
        run = start_run(goal, current, future, gap, started_at=STARTED)
        finished = fail_run(run, completed_at=FINISHED)
        assert finished.status is BackcastingRunStatus.FAILED

    def test_run_finishes_only_once(self, context) -> None:
        goal, current, future, gap = context
        run = start_run(goal, current, future, gap, started_at=STARTED)
        finished = complete_run(run, completed_at=FINISHED)
        with pytest.raises(BackcastingRunError):
            complete_run(finished, completed_at=FINISHED + timedelta(seconds=1))
        with pytest.raises(BackcastingRunError):
            fail_run(finished, completed_at=FINISHED + timedelta(seconds=1))

    def test_finish_time_must_not_precede_start(self, context) -> None:
        goal, current, future, gap = context
        run = start_run(goal, current, future, gap, started_at=STARTED)
        with pytest.raises(BackcastingRunError):
            complete_run(run, completed_at=STARTED - timedelta(seconds=1))
