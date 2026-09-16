"""Tests for local replan (TASK-085).

Level 2 at its narrowest: one task revised in place, the
Goal/Future untouched, the change traced as a plan version.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.local_replan import (
    LocalReplan,
    LocalReplanError,
    replan_task_locally,
)
from backcasting.domain.plan import create_plan
from backcasting.domain.plan_version import PlanChangeSet
from backcasting.domain.replanning_policy import ReplanScope
from backcasting.domain.task import create_task, revise_task

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
REVISED = datetime(2026, 6, 2, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


@pytest.fixture
def task(plan):
    return revise_task(
        create_task(plan, "Draft the migration", created_at=CREATED),
        duration=4 * HOUR,
        updated_at=CREATED,
    )


class TestLocalReplanRecord:
    def _version(self, plan):
        from backcasting.domain.plan_version import PlanVersion

        return PlanVersion(
            version_id=uuid.uuid4(),
            plan_id=plan.plan_id,
            version=1,
            reason="Re-estimate after persistent slippage",
            change_set=PlanChangeSet(revised_task_id=uuid.uuid4()),
            created_at=REVISED,
        )

    def test_shape(self, plan, task) -> None:
        version = self._version(plan)
        replan = LocalReplan(ReplanScope.LOCAL, plan, task, version)
        assert replan.scope is ReplanScope.LOCAL
        assert replan.plan is plan
        assert replan.task is task

    def test_scope_must_be_local(self, plan, task) -> None:
        with pytest.raises(LocalReplanError, match="scope must be LOCAL"):
            LocalReplan(
                ReplanScope.GLOBAL, plan, task, self._version(plan)
            )

    def test_rejects_bad_fields(self, plan, task) -> None:
        version = self._version(plan)
        with pytest.raises(LocalReplanError, match="plan must be"):
            LocalReplan(ReplanScope.LOCAL, "plan", task, version)  # type: ignore[arg-type]
        with pytest.raises(LocalReplanError, match="task must be"):
            LocalReplan(ReplanScope.LOCAL, plan, "task", version)  # type: ignore[arg-type]
        with pytest.raises(LocalReplanError, match="version must be"):
            LocalReplan(ReplanScope.LOCAL, plan, task, "version")  # type: ignore[arg-type]

    def test_rejects_mismatched_ownership(self, plan, task) -> None:
        other_plan = create_plan(
            create_goal(uuid.uuid4(), "Other", created_at=CREATED),
            10 * HOUR,
            created_at=CREATED,
        )
        with pytest.raises(LocalReplanError, match="task does not belong"):
            LocalReplan(
                ReplanScope.LOCAL, other_plan, task, self._version(other_plan)
            )
        with pytest.raises(LocalReplanError, match="version does not belong"):
            LocalReplan(
                ReplanScope.LOCAL, plan, task, self._version(other_plan)
            )


class TestReplanTaskLocally:
    def test_re_estimate_moves_the_workload_and_traces_the_version(
        self, plan, task
    ) -> None:
        replan = replan_task_locally(
            plan,
            (),
            task,
            reason="The migration ran long twice; the estimate was wrong",
            duration=6 * HOUR,
            updated_at=REVISED,
        )
        assert replan.task.duration == 6 * HOUR
        assert replan.task.updated_at == REVISED
        assert replan.plan.workload == 22 * HOUR  # 20h + the 2h delta
        assert replan.version.version == 1
        assert replan.version.change_set.workload == 22 * HOUR
        assert replan.version.change_set.revised_task_id == task.task_id

    def test_goal_and_future_stay_untouched(self, plan, task) -> None:
        """Level 2's defining constraint: the plan's identity and
        provenance carry over — only the content moved."""
        replan = replan_task_locally(
            plan, (), task, reason="Re-estimate", duration=6 * HOUR,
            updated_at=REVISED,
        )
        assert replan.plan.plan_id == plan.plan_id
        assert replan.plan.goal_id == plan.goal_id
        assert replan.plan.created_at == plan.created_at
        assert replan.task.task_id == task.task_id
        assert replan.task.plan_id == task.plan_id

    def test_shrinking_an_estimate_shrinks_the_workload(
        self, plan, task
    ) -> None:
        replan = replan_task_locally(
            plan, (), task, reason="Half the work is already done",
            duration=2 * HOUR, updated_at=REVISED,
        )
        assert replan.plan.workload == 18 * HOUR

    def test_an_estimate_landing_grows_the_workload_by_itself(
        self, plan
    ) -> None:
        unestimated = create_task(plan, "Review the plan", created_at=CREATED)
        replan = replan_task_locally(
            plan, (), unestimated, reason="First estimate",
            duration=3 * HOUR, updated_at=REVISED,
        )
        assert replan.plan.workload == 23 * HOUR
        assert replan.task.duration == 3 * HOUR

    def test_deadline_only_change_is_meaningful_without_moving_workload(
        self, plan, task
    ) -> None:
        """A re-committed deadline changes the plan's content without
        changing its size; the version names the task."""
        new_deadline = datetime(2026, 10, 1, tzinfo=timezone.utc)
        replan = replan_task_locally(
            plan, (), task, reason="Committee moved the review",
            deadline=new_deadline, updated_at=REVISED,
        )
        assert replan.plan.workload == 20 * HOUR  # unchanged
        assert replan.task.deadline == new_deadline
        assert replan.version.change_set.workload is None
        assert replan.version.change_set.revised_task_id == task.task_id

    def test_title_and_description_move_too(self, plan, task) -> None:
        replan = replan_task_locally(
            plan, (), task, reason="Renamed for clarity",
            title="Draft the v2 migration", duration=4 * HOUR,
            updated_at=REVISED,
        )
        assert replan.task.title == "Draft the v2 migration"

    def test_a_revision_that_changes_nothing_is_rejected(
        self, plan, task
    ) -> None:
        with pytest.raises(LocalReplanError, match="changes nothing"):
            replan_task_locally(
                plan, (), task, reason="No-op", updated_at=REVISED
            )
        with pytest.raises(LocalReplanError, match="changes nothing"):
            replan_task_locally(
                plan, (), task, reason="Same estimate", duration=4 * HOUR,
                updated_at=REVISED,
            )

    def test_version_numbering_continues_the_history(
        self, plan, task
    ) -> None:
        first = replan_task_locally(
            plan, (), task, reason="Re-estimate", duration=5 * HOUR,
            updated_at=REVISED,
        )
        second = replan_task_locally(
            first.plan,
            (first.version,),
            first.task,
            reason="Re-estimate again",
            duration=6 * HOUR,
            updated_at=REVISED + HOUR,
        )
        assert second.version.version == 2
        assert second.plan.workload == 22 * HOUR

    def test_workload_cannot_go_negative(self, plan) -> None:
        """A 1h plan whose only task shrinks from 4h to 1h: the plan
        never had that 4h — the plan-version invariant surfaces it."""
        tiny = create_plan(
            create_goal(uuid.uuid4(), "Tiny", created_at=CREATED),
            1 * HOUR,
            created_at=CREATED,
        )
        task = revise_task(
            create_task(tiny, "Task", created_at=CREATED),
            duration=4 * HOUR,
            updated_at=CREATED,
        )
        with pytest.raises(Exception, match="non-negative"):
            replan_task_locally(
                tiny, (), task, reason="Shrink", duration=1 * HOUR,
                updated_at=REVISED,
            )

    def test_source_run_provenance_carries(self, plan, task) -> None:
        run_id = uuid.uuid4()
        replan = replan_task_locally(
            plan, (), task, reason="Re-estimate", duration=6 * HOUR,
            source_run_id=run_id, updated_at=REVISED,
        )
        assert replan.version.source_run_id == run_id

    def test_rejects_bad_arguments(self, plan, task) -> None:
        with pytest.raises(LocalReplanError, match="plan must be"):
            replan_task_locally(
                "plan", (), task, reason="x", duration=6 * HOUR  # type: ignore[arg-type]
            )
        with pytest.raises(LocalReplanError, match="history must be"):
            replan_task_locally(
                plan, [], task, reason="x", duration=6 * HOUR  # type: ignore[arg-type]
            )
        with pytest.raises(LocalReplanError, match="task must be"):
            replan_task_locally(
                plan, (), "task", reason="x", duration=6 * HOUR  # type: ignore[arg-type]
            )

    def test_task_of_another_plan_is_rejected(self, plan) -> None:
        other_plan = create_plan(
            create_goal(uuid.uuid4(), "Other", created_at=CREATED),
            10 * HOUR,
            created_at=CREATED,
        )
        foreign = revise_task(
            create_task(other_plan, "Foreign", created_at=CREATED),
            duration=2 * HOUR,
            updated_at=CREATED,
        )
        with pytest.raises(LocalReplanError, match="does not belong"):
            replan_task_locally(
                plan, (), foreign, reason="x", duration=6 * HOUR,
                updated_at=REVISED,
            )


class TestWiring:
    def test_decide_then_replan_locally(self, plan, task) -> None:
        """The full arc: a persistent slip decides REPLAN, and the
        local scope answers with one task's re-estimate."""
        from backcasting.domain.cooldown import Cooldown
        from backcasting.domain.decision_engine import (
            DecisionAction,
            decide_response,
        )
        from backcasting.domain.persistence import (
            Persistence,
            PersistenceReading,
        )
        from backcasting.domain.replanning_policy import (
            ReplanningLevel,
            ReplanningMode,
            ReplanningPolicy,
        )
        from backcasting.domain.trigger import TriggerKind, raise_trigger

        MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)
        at = MONDAY + timedelta(days=7)
        trigger = raise_trigger(
            TriggerKind.PROGRESS,
            "Estimate ran long; the work needs more than 4h.",
            observed_at=at,
        )
        policy = ReplanningPolicy(
            ReplanningMode.AUTOMATIC, Cooldown(timedelta(days=7)), Persistence(1)
        )
        decision = decide_response(
            policy,
            PersistenceReading(active=True, consecutive=1),
            (ReplanningLevel.REPLAN,),
            at=trigger.observed_at,
        )
        assert decision.action is DecisionAction.ACT
        assert decision.level is ReplanningLevel.REPLAN

        replan = replan_task_locally(
            plan,
            (),
            task,
            reason=trigger.detail,
            duration=6 * HOUR,
            updated_at=at,
        )
        assert replan.version.reason == trigger.detail
        assert replan.task.duration == 6 * HOUR
        assert replan.plan.workload == 22 * HOUR
