"""Tests for task dependencies (TASK-051).

Pins the ordering layer of the scheduling hierarchy ("… existing
commitments → dependencies → …", docs/05): finish-to-start links,
cycle-proof appending, and deterministic topological order.
"""

from __future__ import annotations

import uuid
from datetime import timedelta, timezone
from datetime import datetime

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.task import create_task
from backcasting.domain.task_dependency import (
    TaskDependency,
    TaskDependencyError,
    add_dependency,
    all_prerequisites,
    blocks,
    create_dependency,
    depends_on,
    has_path,
    topological_order,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, title):
    return create_task(plan, title, created_at=CREATED)


class TestCreateDependency:
    def test_links_two_tasks(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        link = create_dependency(second, first)
        assert link.task_id == second.task_id
        assert link.depends_on_task_id == first.task_id

    def test_cross_plan_link_is_rejected(self, plan) -> None:
        other_plan = create_plan(
            create_goal(uuid.uuid4(), "Other", created_at=CREATED),
            HOUR,
            created_at=CREATED,
        )
        with pytest.raises(TaskDependencyError, match="crosses plans"):
            create_dependency(_task(plan, "A"), _task(other_plan, "B"))

    def test_self_dependency_is_rejected(self, plan) -> None:
        task = _task(plan, "Loop")
        with pytest.raises(TaskDependencyError, match="cannot depend on itself"):
            TaskDependency(task_id=task.task_id, depends_on_task_id=task.task_id)

    def test_non_uuid_ids_are_rejected(self) -> None:
        with pytest.raises(TaskDependencyError, match="task_id must be a UUID"):
            TaskDependency(task_id="a", depends_on_task_id=uuid.uuid4())

    def test_rejects_non_tasks(self) -> None:
        with pytest.raises(TypeError, match="task must be a Task"):
            create_dependency("task", "on")  # type: ignore[arg-type]


class TestAddDependency:
    def test_appends_valid_link(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        links = add_dependency((), second, first)
        assert links == (TaskDependency(second.task_id, first.task_id),)

    def test_duplicate_link_is_rejected(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        links = add_dependency((), second, first)
        with pytest.raises(TaskDependencyError, match="already exists"):
            add_dependency(links, second, first)

    def test_direct_cycle_is_rejected(self, plan) -> None:
        first = _task(plan, "Draft")
        second = _task(plan, "Review")
        links = add_dependency((), second, first)
        with pytest.raises(TaskDependencyError, match="cycle"):
            add_dependency(links, first, second)

    def test_transitive_cycle_is_rejected(self, plan) -> None:
        a = _task(plan, "A")
        b = _task(plan, "B")
        c = _task(plan, "C")
        links = add_dependency(add_dependency((), b, a), c, b)
        # c → b → a exists; adding a → c would close the loop.
        with pytest.raises(TaskDependencyError, match="cycle"):
            add_dependency(links, a, c)

    def test_long_chain_is_allowed(self, plan) -> None:
        tasks = [_task(plan, f"T{i}") for i in range(10)]
        links = ()
        for later, earlier in zip(tasks[1:], tasks):
            links = add_dependency(links, later, earlier)
        assert len(links) == 9

    def test_non_tuple_collection_is_rejected(self, plan) -> None:
        with pytest.raises(TaskDependencyError, match="dependencies must be"):
            add_dependency(
                [], _task(plan, "A"), _task(plan, "B")  # type: ignore[arg-type]
            )


class TestQueries:
    def _chain(self, plan):
        a = _task(plan, "A")
        b = _task(plan, "B")
        c = _task(plan, "C")
        links = add_dependency(add_dependency((), b, a), c, b)
        return a, b, c, links

    def test_depends_on_lists_direct_prerequisites(self, plan) -> None:
        a, b, c, links = self._chain(plan)
        assert depends_on(links, a.task_id) == frozenset()
        assert depends_on(links, b.task_id) == frozenset({a.task_id})
        assert depends_on(links, c.task_id) == frozenset({b.task_id})

    def test_blocks_lists_direct_dependents(self, plan) -> None:
        a, b, c, links = self._chain(plan)
        assert blocks(links, a.task_id) == frozenset({b.task_id})
        assert blocks(links, c.task_id) == frozenset()

    def test_all_prerequisites_is_transitive(self, plan) -> None:
        a, b, c, links = self._chain(plan)
        assert all_prerequisites(links, c.task_id) == frozenset(
            {a.task_id, b.task_id}
        )
        assert all_prerequisites(links, a.task_id) == frozenset()

    def test_all_prerequisites_counts_diamond_once(self, plan) -> None:
        d = _task(plan, "D")
        b = _task(plan, "B")
        c = _task(plan, "C")
        a = _task(plan, "A")
        links = ()
        links = add_dependency(links, b, d)
        links = add_dependency(links, c, d)
        links = add_dependency(links, a, b)
        links = add_dependency(links, a, c)
        assert all_prerequisites(links, a.task_id) == frozenset(
            {b.task_id, c.task_id, d.task_id}
        )

    def test_has_path_follows_chains(self, plan) -> None:
        a, b, c, links = self._chain(plan)
        assert has_path(links, a.task_id, c.task_id)
        assert not has_path(links, c.task_id, a.task_id)
        assert not has_path(links, a.task_id, uuid.uuid4())

    def test_non_uuid_task_id_is_rejected(self, plan) -> None:
        with pytest.raises(TaskDependencyError, match="task_id must be a UUID"):
            depends_on((), "task")


class TestTopologicalOrder:
    def test_chain_orders_earliest_first(self, plan) -> None:
        a = _task(plan, "A")
        b = _task(plan, "B")
        c = _task(plan, "C")
        links = add_dependency(add_dependency((), b, a), c, b)
        ordered = topological_order((c, b, a), links)
        assert [task.title for task in ordered] == ["A", "B", "C"]

    def test_diamond(self, plan) -> None:
        d = _task(plan, "D")
        b = _task(plan, "B")
        c = _task(plan, "C")
        a = _task(plan, "A")
        links = ()
        links = add_dependency(links, b, d)
        links = add_dependency(links, c, d)
        links = add_dependency(links, a, b)
        links = add_dependency(links, a, c)
        ordered = topological_order((a, b, c, d), links)
        assert ordered[0] is d
        assert ordered[-1] is a
        assert {ordered[1], ordered[2]} == {b, c}

    def test_order_is_stable_on_input(self, plan) -> None:
        a = _task(plan, "A")
        b = _task(plan, "B")
        links = add_dependency((), b, a)
        first = topological_order((a, b), links)
        second = topological_order((a, b), links)
        assert first == second

    def test_independent_tasks_keep_input_order(self, plan) -> None:
        a = _task(plan, "A")
        b = _task(plan, "B")
        ordered = topological_order((b, a), ())
        assert ordered == (b, a)

    def test_cycle_raises(self, plan) -> None:
        a = _task(plan, "A")
        b = _task(plan, "B")
        # Bypass add_dependency to simulate a corrupted collection.
        links = (
            TaskDependency(a.task_id, b.task_id),
            TaskDependency(b.task_id, a.task_id),
        )
        with pytest.raises(TaskDependencyError, match="cycle"):
            topological_order((a, b), links)

    def test_foreign_link_reference_raises(self, plan) -> None:
        a = _task(plan, "A")
        outsider = _task(plan, "Outsider")
        links = (TaskDependency(a.task_id, outsider.task_id),)
        with pytest.raises(TaskDependencyError, match="outside the collection"):
            topological_order((a,), links)

    def test_duplicate_task_ids_raise(self, plan) -> None:
        a = _task(plan, "A")
        with pytest.raises(TaskDependencyError, match="unique ids"):
            topological_order((a, a), ())

    def test_non_tuple_tasks_are_rejected(self, plan) -> None:
        with pytest.raises(TaskDependencyError, match="tasks must be"):
            topological_order([_task(plan, "A")], ())  # type: ignore[arg-type]
