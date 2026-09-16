"""Tests for regional replan (TASK-086).

Level 2 at middle scope: a dependency-connected group of tasks
revised as one decision, one reason, one plan version.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.plan_version import PlanChangeSet, PlanVersion
from backcasting.domain.regional_replan import (
    RegionalReplan,
    RegionalReplanError,
    TaskRevision,
    dependency_region,
    replan_tasks_regionally,
)
from backcasting.domain.replanning_policy import ReplanScope
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.task_dependency import add_dependency

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


class TestTaskRevision:
    def test_holds_before_and_after(self, plan) -> None:
        before = _task(plan, "Draft", 4)
        after = revise_task(before, duration=6 * HOUR, updated_at=REVISED)
        revision = TaskRevision(before, after)
        assert revision.before is before
        assert revision.after is after

    def test_identity_must_be_kept(self, plan) -> None:
        with pytest.raises(RegionalReplanError, match="two tasks"):
            TaskRevision(_task(plan, "Draft", 4), _task(plan, "Other", 4))

    def test_a_revision_must_change_something(self, plan) -> None:
        before = _task(plan, "Draft", 4)
        after = revise_task(before, updated_at=REVISED)  # only the stamp moves
        with pytest.raises(RegionalReplanError, match="changes nothing"):
            TaskRevision(before, after)

    def test_rejects_non_tasks(self, plan) -> None:
        with pytest.raises(RegionalReplanError, match="before must be"):
            TaskRevision("before", _task(plan, "Draft", 4))  # type: ignore[arg-type]
        with pytest.raises(RegionalReplanError, match="after must be"):
            TaskRevision(_task(plan, "Draft", 4), "after")  # type: ignore[arg-type]


class TestDependencyRegion:
    def test_a_lone_task_is_its_own_region(self, plan) -> None:
        lone = _task(plan, "Lone", 2)
        assert dependency_region(lone, (lone,), ()) == (lone,)

    def test_prerequisites_and_dependents_join(self, plan) -> None:
        """A re-estimate moves work on both sides: everything the seed
        waits on, and everything waiting on the seed."""
        research = _task(plan, "Research", 2)
        draft = _task(plan, "Draft", 4)
        review = _task(plan, "Review", 1)
        ship = _task(plan, "Ship", 1)
        unrelated = _task(plan, "Unrelated", 3)
        dependencies = ()
        dependencies = add_dependency(dependencies, draft, research)
        dependencies = add_dependency(dependencies, review, draft)
        dependencies = add_dependency(dependencies, ship, review)

        region = dependency_region(
            draft, (research, draft, review, ship, unrelated), dependencies
        )
        assert set(t.title for t in region) == {"Research", "Draft", "Review", "Ship"}
        assert unrelated not in region
        # Topological: research before draft before review before ship.
        titles = [t.title for t in region]
        assert titles.index("Research") < titles.index("Draft")
        assert titles.index("Draft") < titles.index("Review")
        assert titles.index("Review") < titles.index("Ship")

    def test_an_unrelated_chain_stays_out(self, plan) -> None:
        seed = _task(plan, "Seed", 2)
        other_a = _task(plan, "Other A", 2)
        other_b = _task(plan, "Other B", 2)
        dependencies = add_dependency((), other_b, other_a)
        region = dependency_region(
            seed, (seed, other_a, other_b), dependencies
        )
        assert region == (seed,)

    def test_seed_must_be_among_the_tasks(self, plan) -> None:
        stranger = _task(plan, "Stranger", 2)
        with pytest.raises(RegionalReplanError, match="seed must be among"):
            dependency_region(stranger, (), ())

    def test_rejects_bad_arguments(self, plan) -> None:
        task = _task(plan, "Task", 2)
        with pytest.raises(RegionalReplanError, match="seed must be a"):
            dependency_region("seed", (task,), ())  # type: ignore[arg-type]
        with pytest.raises(RegionalReplanError, match="tasks must be a tuple"):
            dependency_region(task, [task], ())  # type: ignore[arg-type]
        with pytest.raises(RegionalReplanError, match="Task instances"):
            dependency_region(task, ("x",), ())  # type: ignore[arg-type]


class TestRegionalReplanRecord:
    def _version(self, plan):
        return PlanVersion(
            version_id=uuid.uuid4(),
            plan_id=plan.plan_id,
            version=1,
            reason="The migration region re-estimated",
            change_set=PlanChangeSet(revised_task_ids=(uuid.uuid4(),)),
            created_at=REVISED,
        )

    def test_shape(self, plan) -> None:
        task = _task(plan, "Draft", 6)
        version = self._version(plan)
        replan = RegionalReplan(
            ReplanScope.REGIONAL, plan, (task,), version
        )
        assert replan.scope is ReplanScope.REGIONAL
        assert replan.tasks == (task,)

    def test_scope_must_be_regional(self, plan) -> None:
        with pytest.raises(RegionalReplanError, match="scope must be REGIONAL"):
            RegionalReplan(
                ReplanScope.LOCAL, plan, (), self._version(plan)
            )

    def test_rejects_bad_fields(self, plan) -> None:
        version = self._version(plan)
        with pytest.raises(RegionalReplanError, match="plan must be"):
            RegionalReplan(ReplanScope.REGIONAL, "plan", (), version)  # type: ignore[arg-type]
        with pytest.raises(RegionalReplanError, match="tasks must be a tuple"):
            RegionalReplan(ReplanScope.REGIONAL, plan, [], version)  # type: ignore[arg-type]
        with pytest.raises(RegionalReplanError, match="version must be"):
            RegionalReplan(ReplanScope.REGIONAL, plan, (), "version")  # type: ignore[arg-type]

    def test_rejects_foreign_tasks(self, plan) -> None:
        other_plan = create_plan(
            create_goal(uuid.uuid4(), "Other", created_at=CREATED),
            10 * HOUR,
            created_at=CREATED,
        )
        foreign = _task(other_plan, "Foreign", 2)
        with pytest.raises(RegionalReplanError, match="does not belong"):
            RegionalReplan(
                ReplanScope.REGIONAL, plan, (foreign,), self._version(plan)
            )
        with pytest.raises(RegionalReplanError, match="version does not belong"):
            RegionalReplan(
                ReplanScope.REGIONAL, plan, (), self._version(other_plan)
            )


class TestReplanTasksRegionally:
    def _revision(self, task, hours):
        return TaskRevision(
            task,
            revise_task(task, duration=timedelta(hours=hours), updated_at=REVISED),
        )

    def test_one_version_for_the_whole_region(self, plan) -> None:
        research = _task(plan, "Research", 2)
        draft = _task(plan, "Draft", 4)
        replan = replan_tasks_regionally(
            plan,
            (),
            (self._revision(research, 3), self._revision(draft, 6)),
            reason="The migration ran long; research and draft re-estimated",
            at=REVISED,
        )
        assert replan.plan.workload == 23 * HOUR  # 20h + 1h + 2h
        assert replan.version.version == 1
        assert replan.version.change_set.workload == 23 * HOUR
        assert set(replan.version.change_set.revised_task_ids) == {
            research.task_id,
            draft.task_id,
        }
        assert {t.title for t in replan.tasks} == {"Research", "Draft"}

    def test_deltas_in_opposite_directions_net_out(self, plan) -> None:
        research = _task(plan, "Research", 2)
        draft = _task(plan, "Draft", 4)
        replan = replan_tasks_regionally(
            plan,
            (),
            (self._revision(research, 4), self._revision(draft, 2)),
            reason="Work moves from draft to research",
            at=REVISED,
        )
        assert replan.plan.workload == 20 * HOUR  # net zero

    def test_an_estimate_landing_counts_in_full(self, plan) -> None:
        unestimated = create_task(plan, "Review", created_at=CREATED)
        replan = replan_tasks_regionally(
            plan,
            (),
            (TaskRevision(
                unestimated,
                revise_task(unestimated, duration=2 * HOUR, updated_at=REVISED),
            ),),
            reason="The review finally has an estimate",
            at=REVISED,
        )
        assert replan.plan.workload == 22 * HOUR

    def test_deadline_only_revisions_are_meaningful(self, plan) -> None:
        draft = _task(plan, "Draft", 4)
        deadline = datetime(2026, 10, 1, tzinfo=timezone.utc)
        replan = replan_tasks_regionally(
            plan,
            (),
            (TaskRevision(
                draft,
                revise_task(draft, deadline=deadline, updated_at=REVISED),
            ),),
            reason="The committee moved the review",
            at=REVISED,
        )
        assert replan.plan.workload == 20 * HOUR
        assert replan.version.change_set.workload is None
        assert replan.version.change_set.revised_task_ids == (draft.task_id,)

    def test_version_numbering_continues_the_history(self, plan) -> None:
        draft = _task(plan, "Draft", 4)
        first = replan_tasks_regionally(
            plan, (), (self._revision(draft, 5),),
            reason="First", at=REVISED,
        )
        second = replan_tasks_regionally(
            first.plan, (first.version,),
            (self._revision(first.tasks[0], 6),),
            reason="Second", at=REVISED + HOUR,
        )
        assert second.version.version == 2

    def test_empty_revisions_are_rejected(self, plan) -> None:
        with pytest.raises(RegionalReplanError, match="at least one task"):
            replan_tasks_regionally(plan, (), (), reason="Nothing", at=REVISED)

    def test_a_task_cannot_be_revised_twice(self, plan) -> None:
        draft = _task(plan, "Draft", 4)
        with pytest.raises(RegionalReplanError, match="revised twice"):
            replan_tasks_regionally(
                plan,
                (),
                (self._revision(draft, 5), self._revision(draft, 6)),
                reason="Twice", at=REVISED,
            )

    def test_rejects_bad_arguments(self, plan) -> None:
        draft = _task(plan, "Draft", 4)
        with pytest.raises(RegionalReplanError, match="plan must be"):
            replan_tasks_regionally(
                "plan", (), (self._revision(draft, 5),), reason="x"  # type: ignore[arg-type]
            )
        with pytest.raises(RegionalReplanError, match="history must be"):
            replan_tasks_regionally(
                plan, [], (self._revision(draft, 5),), reason="x"  # type: ignore[arg-type]
            )
        with pytest.raises(RegionalReplanError, match="TaskRevision instances"):
            replan_tasks_regionally(
                plan, (), (draft,), reason="x"  # type: ignore[arg-type]
            )

    def test_foreign_revisions_are_rejected(self, plan) -> None:
        other_plan = create_plan(
            create_goal(uuid.uuid4(), "Other", created_at=CREATED),
            10 * HOUR,
            created_at=CREATED,
        )
        foreign = _task(other_plan, "Foreign", 2)
        with pytest.raises(RegionalReplanError, match="does not belong"):
            replan_tasks_regionally(
                plan, (), (self._revision(foreign, 3),), reason="x", at=REVISED
            )


class TestWiring:
    def test_the_region_moves_as_one_decision(self, plan) -> None:
        """The full regional story: the slip sits on the draft task,
        its region is the dependency-connected group, and the whole
        region is re-estimated as one plan version."""
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

        research = _task(plan, "Research", 2)
        draft = _task(plan, "Draft", 4)
        review = _task(plan, "Review", 1)
        unrelated = _task(plan, "Unrelated", 3)
        dependencies = add_dependency((), draft, research)
        dependencies = add_dependency(dependencies, review, draft)

        region = dependency_region(
            draft, (research, draft, review, unrelated), dependencies
        )
        assert set(t.title for t in region) == {"Research", "Draft", "Review"}

        policy = ReplanningPolicy(
            ReplanningMode.AUTOMATIC,
            Cooldown(timedelta(days=7)),
            Persistence(1),
        )
        decision = decide_response(
            policy,
            PersistenceReading(active=True, consecutive=1),
            (ReplanningLevel.REPLAN,),
            at=REVISED,
        )
        assert decision.action is DecisionAction.ACT

        revisions = tuple(
            TaskRevision(
                task,
                revise_task(
                    task,
                    duration=task.duration + HOUR,  # one hour more across the region
                    updated_at=REVISED,
                ),
            )
            for task in region
        )
        replan = replan_tasks_regionally(
            plan, (), revisions, reason="The migration region slipped", at=REVISED
        )
        assert replan.plan.workload == 23 * HOUR  # 20h + 3h across three tasks
        assert set(replan.version.change_set.revised_task_ids) == {
            t.task_id for t in region
        }
        assert unrelated.task_id not in replan.version.change_set.revised_task_ids
