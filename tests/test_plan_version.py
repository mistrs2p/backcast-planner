"""Tests for plan versioning (TASK-048).

Pins the traceable replan history: every meaningful change to a plan
produces a version with reason, source run, and change set
(docs/08-REPLANNING-MODEL.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.plan_version import (
    PlanChangeSet,
    PlanVersion,
    PlanVersionError,
    apply_plan_version,
    latest_version,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
REVISED_AT = datetime(2026, 1, 3, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(
        goal, 20 * HOUR, title="Focus week", created_at=CREATED
    )


class TestPlanChangeSet:
    def test_defaults_change_nothing(self) -> None:
        change_set = PlanChangeSet()
        assert change_set.title is None
        assert change_set.workload is None

    def test_negative_workload_is_rejected(self) -> None:
        with pytest.raises(PlanVersionError, match="non-negative timedelta"):
            PlanChangeSet(workload=-HOUR)

    def test_long_title_is_rejected(self) -> None:
        with pytest.raises(PlanVersionError, match="at most 200"):
            PlanChangeSet(title="x" * 201)


class TestPlanVersionRecord:
    def _version(self, **overrides) -> PlanVersion:
        fields = dict(
            version_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),
            version=1,
            reason="Weekly replan",
            change_set=PlanChangeSet(workload=18 * HOUR),
            created_at=CREATED,
        )
        fields.update(overrides)
        return PlanVersion(**fields)

    def test_valid_version_is_accepted(self) -> None:
        version = self._version()
        assert version.version == 1
        assert version.reason == "Weekly replan"
        assert version.source_run_id is None

    def test_reason_is_stripped(self) -> None:
        version = self._version(reason="  Weekly replan  ")
        assert version.reason == "Weekly replan"

    def test_empty_reason_is_rejected(self) -> None:
        for empty in ("", "   "):
            with pytest.raises(PlanVersionError, match="reason must not be empty"):
                self._version(reason=empty)

    def test_long_reason_is_rejected(self) -> None:
        with pytest.raises(PlanVersionError, match="at most 500"):
            self._version(reason="x" * 501)

    def test_non_positive_version_is_rejected(self) -> None:
        with pytest.raises(PlanVersionError, match="at least 1"):
            self._version(version=0)

    def test_non_uuid_ids_are_rejected(self) -> None:
        with pytest.raises(PlanVersionError, match="version_id must be a UUID"):
            self._version(version_id="id")
        with pytest.raises(PlanVersionError, match="plan_id must be a UUID"):
            self._version(plan_id="plan")
        with pytest.raises(PlanVersionError, match="source_run_id must be"):
            self._version(source_run_id="run")

    def test_naive_created_at_is_rejected(self) -> None:
        with pytest.raises(PlanVersionError, match="created_at"):
            self._version(created_at=datetime(2026, 1, 1))

    def test_bad_change_set_is_rejected(self) -> None:
        with pytest.raises(PlanVersionError, match="change_set must be"):
            self._version(change_set="changes")  # type: ignore[arg-type]


class TestApplyPlanVersion:
    def test_first_version_is_numbered_one(self, plan) -> None:
        revised, version = apply_plan_version(
            plan,
            (),
            reason="Capacity dropped",
            change_set=PlanChangeSet(workload=15 * HOUR),
            at=REVISED_AT,
        )
        assert version.version == 1
        assert version.plan_id == plan.plan_id
        assert revised.workload == 15 * HOUR
        assert revised.title == plan.title
        assert revised.status == plan.status  # content only, no status move
        assert revised.updated_at == REVISED_AT

    def test_version_numbers_increase(self, plan) -> None:
        first, v1 = apply_plan_version(
            plan,
            (),
            reason="Capacity dropped",
            change_set=PlanChangeSet(workload=15 * HOUR),
            at=REVISED_AT,
        )
        second, v2 = apply_plan_version(
            first,
            (v1,),
            reason="Scope trimmed",
            change_set=PlanChangeSet(title="Focus sprint", workload=12 * HOUR),
            at=REVISED_AT,
        )
        assert v1.version == 1
        assert v2.version == 2
        assert second.title == "Focus sprint"
        assert second.workload == 12 * HOUR

    def test_partial_change_sets_keep_other_fields(self, plan) -> None:
        revised, _ = apply_plan_version(
            plan,
            (),
            reason="Retitled",
            change_set=PlanChangeSet(title="Focus sprint"),
            at=REVISED_AT,
        )
        assert revised.title == "Focus sprint"
        assert revised.workload == plan.workload

    def test_source_run_provenance_is_recorded(self, plan) -> None:
        run_id = uuid.uuid4()
        _, version = apply_plan_version(
            plan,
            (),
            reason="Replanned by run",
            change_set=PlanChangeSet(workload=15 * HOUR),
            source_run_id=run_id,
            at=REVISED_AT,
        )
        assert version.source_run_id == run_id

    def test_no_op_change_set_is_rejected(self, plan) -> None:
        with pytest.raises(PlanVersionError, match="meaningful"):
            apply_plan_version(
                plan,
                (),
                reason="Nothing changed",
                change_set=PlanChangeSet(),
                at=REVISED_AT,
            )
        # Same values as the plan already holds is equally meaningless.
        with pytest.raises(PlanVersionError, match="meaningful"):
            apply_plan_version(
                plan,
                (),
                reason="Echo",
                change_set=PlanChangeSet(
                    title="Focus week", workload=20 * HOUR
                ),
                at=REVISED_AT,
            )

    def test_foreign_history_is_rejected(self, plan) -> None:
        foreign = PlanVersion(
            version_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),  # some other plan's trail
            version=1,
            reason="Other plan",
            change_set=PlanChangeSet(workload=1 * HOUR),
            created_at=REVISED_AT,
        )
        with pytest.raises(PlanVersionError, match="does not belong"):
            apply_plan_version(
                plan,
                (foreign,),
                reason="Oops",
                change_set=PlanChangeSet(workload=2 * HOUR),
                at=REVISED_AT,
            )

    def test_duplicate_version_numbers_are_rejected(self, plan) -> None:
        _, v1 = apply_plan_version(
            plan,
            (),
            reason="First",
            change_set=PlanChangeSet(workload=15 * HOUR),
            at=REVISED_AT,
        )
        with pytest.raises(PlanVersionError, match="duplicate version"):
            apply_plan_version(
                plan,
                (v1, v1),
                reason="Corrupt history",
                change_set=PlanChangeSet(workload=10 * HOUR),
                at=REVISED_AT,
            )

    def test_history_gaps_do_not_reset_numbering(self, plan) -> None:
        _, v1 = apply_plan_version(
            plan,
            (),
            reason="First",
            change_set=PlanChangeSet(workload=15 * HOUR),
            at=REVISED_AT,
        )
        v5 = PlanVersion(
            version_id=uuid.uuid4(),
            plan_id=plan.plan_id,
            version=5,
            reason="Restored from backup",
            change_set=PlanChangeSet(workload=10 * HOUR),
            created_at=REVISED_AT,
        )
        _, v6 = apply_plan_version(
            plan,
            (v1, v5),
            reason="Next",
            change_set=PlanChangeSet(workload=8 * HOUR),
            at=REVISED_AT,
        )
        assert v6.version == 6

    def test_non_tuple_history_is_rejected(self, plan) -> None:
        with pytest.raises(PlanVersionError, match="history must be"):
            apply_plan_version(
                plan,
                [],  # type: ignore[arg-type]
                reason="List",
                change_set=PlanChangeSet(workload=1 * HOUR),
                at=REVISED_AT,
            )

    def test_rejects_non_plan(self) -> None:
        with pytest.raises(TypeError, match="plan must be a Plan"):
            apply_plan_version(
                "plan",  # type: ignore[arg-type]
                (),
                reason="X",
                change_set=PlanChangeSet(workload=1 * HOUR),
            )

    def test_injectable_version_id(self, plan) -> None:
        version_id = uuid.uuid4()
        _, version = apply_plan_version(
            plan,
            (),
            reason="First",
            change_set=PlanChangeSet(workload=15 * HOUR),
            version_id=version_id,
            at=REVISED_AT,
        )
        assert version.version_id == version_id


class TestLatestVersion:
    def test_empty_history_has_no_latest(self) -> None:
        assert latest_version(()) is None

    def test_latest_is_the_highest_number(self, plan) -> None:
        _, v1 = apply_plan_version(
            plan,
            (),
            reason="First",
            change_set=PlanChangeSet(workload=15 * HOUR),
            at=REVISED_AT,
        )
        _, v2 = apply_plan_version(
            plan,
            (v1,),
            reason="Second",
            change_set=PlanChangeSet(workload=10 * HOUR),
            at=REVISED_AT,
        )
        assert latest_version((v1, v2)) is v2
        assert latest_version((v2, v1)) is v2  # order-independent

    def test_non_tuple_history_is_rejected(self) -> None:
        with pytest.raises(PlanVersionError, match="history must be"):
            latest_version([])  # type: ignore[arg-type]
