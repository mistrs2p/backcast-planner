"""Tests for global replan (TASK-087).

Level 2 at its widest: the whole plan re-derived from its task set,
workload recomputed rather than shifted, the Goal/Future untouched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.global_replan import (
    GlobalReplan,
    GlobalReplanError,
    replan_plan_globally,
)
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.plan_version import PlanChangeSet, PlanVersion
from backcasting.domain.replanning_policy import ReplanScope
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.task_estimation import TaskEstimationError

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
REVISED = datetime(2026, 6, 2, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, title, hours):
    task = create_task(plan, title, created_at=CREATED)
    return revise_task(task, duration=timedelta(hours=hours), updated_at=CREATED)


class TestGlobalReplanRecord:
    def _version(self, plan):
        return PlanVersion(
            version_id=uuid.uuid4(),
            plan_id=plan.plan_id,
            version=1,
            reason="The whole plan was re-derived",
            change_set=PlanChangeSet(workload=9 * HOUR),
            created_at=REVISED,
        )

    def test_shape(self, plan) -> None:
        version = self._version(plan)
        replan = GlobalReplan(ReplanScope.GLOBAL, plan, version)
        assert replan.scope is ReplanScope.GLOBAL
        assert replan.plan is plan
        assert replan.version is version

    def test_scope_must_be_global(self, plan) -> None:
        with pytest.raises(GlobalReplanError, match="scope must be GLOBAL"):
            GlobalReplan(ReplanScope.LOCAL, plan, self._version(plan))

    def test_rejects_bad_fields(self, plan) -> None:
        with pytest.raises(GlobalReplanError, match="plan must be"):
            GlobalReplan(ReplanScope.GLOBAL, "plan", self._version(plan))  # type: ignore[arg-type]
        with pytest.raises(GlobalReplanError, match="version must be"):
            GlobalReplan(ReplanScope.GLOBAL, plan, "version")  # type: ignore[arg-type]

    def test_rejects_mismatched_version(self, plan) -> None:
        other_plan = create_plan(
            create_goal(uuid.uuid4(), "Other", created_at=CREATED),
            10 * HOUR,
            created_at=CREATED,
        )
        with pytest.raises(GlobalReplanError, match="does not belong"):
            GlobalReplan(ReplanScope.GLOBAL, plan, self._version(other_plan))


class TestReplanPlanGlobally:
    def test_workload_is_recomputed_not_shifted(self, plan) -> None:
        """The declared 20h was wrong; the three tasks actually sum
        to 9h, and the global replan says so — it does not nudge."""
        tasks = (
            _task(plan, "Research", 2),
            _task(plan, "Draft", 4),
            _task(plan, "Review", 3),
        )
        replan = replan_plan_globally(
            plan, (), tasks, reason="The declared workload never matched the tasks",
            at=REVISED,
        )
        assert replan.plan.workload == 9 * HOUR
        assert replan.version.change_set.workload == 9 * HOUR
        assert replan.version.change_set.revised_task_ids == ()

    def test_title_moves_with_the_rederivation(self, plan) -> None:
        tasks = (_task(plan, "Draft", 4),)
        replan = replan_plan_globally(
            plan, (), tasks, reason="Renamed and re-derived",
            title="Ship v2 — migration only", at=REVISED,
        )
        assert replan.plan.title == "Ship v2 — migration only"

    def test_goal_and_future_stay_untouched(self, plan) -> None:
        tasks = (_task(plan, "Draft", 4),)
        replan = replan_plan_globally(
            plan, (), tasks, reason="Re-derived", at=REVISED,
        )
        assert replan.plan.plan_id == plan.plan_id
        assert replan.plan.goal_id == plan.goal_id
        assert replan.plan.created_at == plan.created_at
        assert replan.plan.run_id == plan.run_id

    def test_a_rederivation_that_changes_nothing_is_rejected(
        self, plan
    ) -> None:
        """20h declared, tasks summing to 20h: re-deriving lands where
        the plan already stands — not a replan."""
        tasks = (_task(plan, "Big", 20),)
        with pytest.raises(Exception, match="changes nothing"):
            replan_plan_globally(
                plan, (), tasks, reason="No-op", at=REVISED,
            )

    def test_unestimated_tasks_surface_the_aggregation_rule(
        self, plan
    ) -> None:
        """A global replan must face its own task set's estimates;
        a missing one is a fact, not a zero."""
        tasks = (_task(plan, "Draft", 4), create_task(plan, "Later", created_at=CREATED))
        with pytest.raises(TaskEstimationError, match="has no estimate"):
            replan_plan_globally(plan, (), tasks, reason="Re-derived", at=REVISED)

    def test_version_numbering_continues_the_history(self, plan) -> None:
        tasks = (_task(plan, "Draft", 4),)
        first = replan_plan_globally(
            plan, (), tasks, reason="First re-derivation", at=REVISED,
        )
        smaller = (_task(plan, "Draft", 2),)
        second = replan_plan_globally(
            first.plan, (first.version,), smaller,
            reason="Second re-derivation", at=REVISED + HOUR,
        )
        assert second.version.version == 2
        assert second.plan.workload == 2 * HOUR

    def test_source_run_provenance_carries(self, plan) -> None:
        run_id = uuid.uuid4()
        tasks = (_task(plan, "Draft", 4),)
        replan = replan_plan_globally(
            plan, (), tasks, reason="Re-derived from the new run",
            source_run_id=run_id, at=REVISED,
        )
        assert replan.version.source_run_id == run_id

    def test_rejects_bad_arguments(self, plan) -> None:
        tasks = (_task(plan, "Draft", 4),)
        with pytest.raises(GlobalReplanError, match="plan must be"):
            replan_plan_globally(
                "plan", (), tasks, reason="x"  # type: ignore[arg-type]
            )
        with pytest.raises(GlobalReplanError, match="history must be"):
            replan_plan_globally(
                plan, [], tasks, reason="x"  # type: ignore[arg-type]
            )
        with pytest.raises(GlobalReplanError, match="tasks must be a tuple"):
            replan_plan_globally(
                plan, (), list(tasks), reason="x"  # type: ignore[arg-type]
            )
        with pytest.raises(GlobalReplanError, match="Task instances"):
            replan_plan_globally(
                plan, (), ("task",), reason="x"  # type: ignore[arg-type]
            )

    def test_foreign_tasks_are_rejected(self, plan) -> None:
        other_plan = create_plan(
            create_goal(uuid.uuid4(), "Other", created_at=CREATED),
            10 * HOUR,
            created_at=CREATED,
        )
        foreign = _task(other_plan, "Foreign", 2)
        with pytest.raises(GlobalReplanError, match="does not belong"):
            replan_plan_globally(
                plan, (), (foreign,), reason="x", at=REVISED
            )


class TestWiring:
    def test_decide_then_replan_globally(self, plan) -> None:
        """The full arc at the widest scope: a persistent systemic
        slip decides REPLAN, the global scope re-derives the plan,
        and the version traces it."""
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

        trigger = raise_trigger(
            TriggerKind.PROGRESS,
            "Every task is slipping; the plan no longer describes reality.",
            observed_at=REVISED,
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

        tasks = (
            _task(plan, "Research", 2),
            _task(plan, "Draft", 4),
            _task(plan, "Review", 3),
        )
        replan = replan_plan_globally(
            plan, (), tasks, reason=trigger.detail, at=REVISED,
        )
        assert replan.version.reason == trigger.detail
        assert replan.plan.workload == 9 * HOUR

    def test_the_three_scopes_share_the_version_trail(self, plan) -> None:
        """Local, regional, then global: one plan, one trail, version
        numbers running through all three scopes."""
        from backcasting.domain.local_replan import replan_task_locally
        from backcasting.domain.regional_replan import (
            TaskRevision,
            replan_tasks_regionally,
        )

        draft = _task(plan, "Draft", 4)
        review = _task(plan, "Review", 3)

        local = replan_task_locally(
            plan, (), draft, reason="Draft re-estimated", duration=6 * HOUR,
            updated_at=REVISED,
        )
        regional = replan_tasks_regionally(
            local.plan,
            (local.version,),
            (TaskRevision(
                review,
                revise_task(review, duration=5 * HOUR, updated_at=REVISED + HOUR),
            ),),
            reason="Review re-estimated",
            at=REVISED + HOUR,
        )
        tasks = (local.task, regional.tasks[0])
        glob = replan_plan_globally(
            regional.plan, (local.version, regional.version), tasks,
            reason="Everything re-derived", at=REVISED + 2 * HOUR,
        )
        assert (local.version.version, regional.version.version, glob.version.version) == (
            1, 2, 3,
        )
        assert glob.plan.workload == 11 * HOUR  # 6 + 5, recomputed
