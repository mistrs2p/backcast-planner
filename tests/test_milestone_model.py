"""Tests for the Milestone domain model (TASK-026).

Covers the intermediate-checkpoint invariants (bounded title, target
date strictly after creation, UTC stamps), the define-during-running-run
guard, and the deliberate absence of a lifecycle (achievement is
expressed through Outcomes).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.backcasting_run import (
    BackcastingRun,
    complete_run,
    fail_run,
    start_run,
)
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.metric import Metric, MetricDirection, MetricKind
from backcasting.domain.milestone import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    Milestone,
    MilestoneError,
    define_milestone,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
CALCULATED = datetime(2026, 1, 6, tzinfo=timezone.utc)
STARTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
DEFINED = STARTED + timedelta(minutes=5)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)
CHECKPOINT = datetime(2026, 6, 1, tzinfo=timezone.utc)


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


class TestMilestone:
    def _valid_kwargs(self) -> dict:
        return {
            "milestone_id": uuid.uuid4(),
            "run_id": uuid.uuid4(),
            "goal_id": uuid.uuid4(),
            "title": "Half-marathon distance",
            "target_date": CHECKPOINT,
            "created_at": DEFINED,
            "updated_at": DEFINED,
        }

    def test_valid_milestone_is_accepted(self) -> None:
        milestone = Milestone(**self._valid_kwargs())
        assert milestone.title == "Half-marathon distance"
        assert milestone.target_date == CHECKPOINT
        assert milestone.description == ""

    def test_title_is_stripped(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["title"] = "  Half-marathon distance  "
        assert Milestone(**kwargs).title == "Half-marathon distance"

    @pytest.mark.parametrize(
        "title",
        ["", "   ", " " * (MAX_TITLE_LENGTH + 1), "x" * (MAX_TITLE_LENGTH + 1)],
    )
    def test_invalid_titles_are_rejected(self, title: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs["title"] = title
        with pytest.raises(MilestoneError):
            Milestone(**kwargs)

    def test_title_at_limit_is_accepted(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["title"] = "x" * MAX_TITLE_LENGTH
        assert Milestone(**kwargs).title == "x" * MAX_TITLE_LENGTH

    def test_description_is_optional_and_bounded(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["description"] = "Comfortably run 21 km."
        assert Milestone(**kwargs).description == "Comfortably run 21 km."
        kwargs["description"] = "x" * (MAX_DESCRIPTION_LENGTH + 1)
        with pytest.raises(MilestoneError):
            Milestone(**kwargs)

    def test_target_date_must_be_after_created_at(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["target_date"] = DEFINED
        with pytest.raises(MilestoneError):
            Milestone(**kwargs)
        kwargs["target_date"] = DEFINED - timedelta(seconds=1)
        with pytest.raises(MilestoneError):
            Milestone(**kwargs)

    @pytest.mark.parametrize("stamp_name", ["target_date", "created_at", "updated_at"])
    def test_stamps_must_be_timezone_aware(self, stamp_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[stamp_name] = datetime(2026, 6, 1)
        with pytest.raises(MilestoneError):
            Milestone(**kwargs)

    @pytest.mark.parametrize("stamp_name", ["target_date", "created_at", "updated_at"])
    def test_stamps_must_be_utc(self, stamp_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[stamp_name] = CHECKPOINT.astimezone(ZoneInfo("Europe/Berlin"))
        with pytest.raises(MilestoneError):
            Milestone(**kwargs)

    def test_updated_at_must_not_precede_created_at(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["updated_at"] = DEFINED - timedelta(seconds=1)
        with pytest.raises(MilestoneError):
            Milestone(**kwargs)

    @pytest.mark.parametrize("field_name", ["milestone_id", "run_id", "goal_id"])
    def test_ids_must_be_uuids(self, field_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[field_name] = "not-a-uuid"
        with pytest.raises(MilestoneError):
            Milestone(**kwargs)

    def test_milestone_is_immutable(self) -> None:
        milestone = Milestone(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            milestone.title = "Other"  # type: ignore[misc]

    def test_milestone_has_no_lifecycle(self) -> None:
        # A milestone is a measurable checkpoint; achievement flows through
        # its Outcomes (Milestone 1:N Outcomes, docs/03), not a status flag.
        assert not hasattr(Milestone, "status")
        assert not hasattr(Milestone, "MilestoneStatus")


class TestDefineMilestone:
    def test_defines_milestone_bound_to_run_and_goal(
        self, running_run: BackcastingRun
    ) -> None:
        milestone = define_milestone(
            running_run, "Half-marathon distance", CHECKPOINT, created_at=DEFINED
        )
        assert isinstance(milestone.milestone_id, uuid.UUID)
        assert milestone.run_id == running_run.run_id
        assert milestone.goal_id == running_run.goal_id
        assert milestone.created_at == DEFINED
        assert milestone.updated_at == DEFINED

    def test_accepts_description(self, running_run: BackcastingRun) -> None:
        milestone = define_milestone(
            running_run,
            "Half-marathon distance",
            CHECKPOINT,
            description="Comfortably run 21 km.",
            created_at=DEFINED,
        )
        assert milestone.description == "Comfortably run 21 km."

    def test_injectable_id_and_clock(self, running_run: BackcastingRun) -> None:
        milestone_id = uuid.uuid4()
        milestone = define_milestone(
            running_run,
            "Half-marathon distance",
            CHECKPOINT,
            milestone_id=milestone_id,
            created_at=DEFINED,
        )
        assert milestone.milestone_id == milestone_id
        assert milestone.created_at == DEFINED

    @pytest.mark.parametrize("finish", [complete_run, fail_run])
    def test_rejects_terminal_runs(self, running_run: BackcastingRun, finish) -> None:
        finished = finish(running_run, completed_at=STARTED + timedelta(minutes=1))
        with pytest.raises(MilestoneError):
            define_milestone(finished, "Too late", CHECKPOINT, created_at=DEFINED)

    def test_rejects_non_run_objects(self) -> None:
        with pytest.raises(TypeError):
            define_milestone("not a run", "Title", CHECKPOINT)  # type: ignore[arg-type]

    def test_validates_target_date_against_creation(
        self, running_run: BackcastingRun
    ) -> None:
        with pytest.raises(MilestoneError):
            define_milestone(
                running_run, "Stale checkpoint", DEFINED, created_at=DEFINED
            )
