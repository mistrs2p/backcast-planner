"""Tests for the resource model (TASK-052).

Pins the "Task N:M Resources" relationship (docs/03): a standalone
catalog entity, required by tasks through an idempotent union on
``resource_ids``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.resource import (
    Resource,
    ResourceError,
    create_resource,
    revise_resource,
    use_resources,
)
from backcasting.domain.task import Task, create_task

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
REVISED = datetime(2026, 1, 2, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


class TestResource:
    def test_minimal_resource(self) -> None:
        resource = create_resource("Laptop", created_at=CREATED)
        assert resource.name == "Laptop"
        assert resource.description == ""
        assert isinstance(resource.resource_id, uuid.UUID)
        assert resource.created_at == CREATED
        assert resource.updated_at == CREATED

    def test_name_is_stripped(self) -> None:
        assert create_resource("  Laptop  ", created_at=CREATED).name == "Laptop"

    def test_empty_name_is_rejected(self) -> None:
        for empty in ("", "   "):
            with pytest.raises(ResourceError, match="non-empty"):
                create_resource(empty)

    def test_long_name_is_rejected(self) -> None:
        with pytest.raises(ResourceError, match="at most 200"):
            create_resource("x" * 201)

    def test_long_description_is_rejected(self) -> None:
        with pytest.raises(ResourceError, match="at most 5000"):
            create_resource("Laptop", description="x" * 5001)

    def test_non_uuid_id_is_rejected(self) -> None:
        with pytest.raises(ResourceError, match="resource_id must be a UUID"):
            Resource(resource_id="id", name="Laptop")

    def test_naive_stamps_are_rejected(self) -> None:
        with pytest.raises(ResourceError, match="created_at"):
            Resource(
                resource_id=uuid.uuid4(),
                name="Laptop",
                created_at=datetime(2026, 1, 1),
            )

    def test_non_utc_stamps_are_rejected(self) -> None:
        from zoneinfo import ZoneInfo

        with pytest.raises(ResourceError, match="must be in UTC"):
            Resource(
                resource_id=uuid.uuid4(),
                name="Laptop",
                created_at=datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Tehran")),
            )

    def test_stamps_must_be_ordered(self) -> None:
        with pytest.raises(ResourceError, match="must not precede"):
            Resource(
                resource_id=uuid.uuid4(),
                name="Laptop",
                created_at=CREATED,
                updated_at=CREATED - timedelta(seconds=1),
            )

    def test_injectable_id_and_clock(self) -> None:
        resource_id = uuid.uuid4()
        resource = create_resource(
            "Laptop", resource_id=resource_id, created_at=CREATED
        )
        assert resource.resource_id == resource_id


class TestReviseResource:
    def test_revision_moves_editable_fields(self) -> None:
        resource = create_resource(
            "Laptop", description="Old.", created_at=CREATED
        )
        revised = revise_resource(
            resource, name="Studio laptop", description="New.", updated_at=REVISED
        )
        assert revised.name == "Studio laptop"
        assert revised.description == "New."
        assert revised.updated_at == REVISED
        assert revised.created_at == CREATED
        assert revised.resource_id == resource.resource_id

    def test_none_keeps_fields(self) -> None:
        resource = create_resource(
            "Laptop", description="Keep.", created_at=CREATED
        )
        revised = revise_resource(resource, updated_at=REVISED)
        assert revised.name == "Laptop"
        assert revised.description == "Keep."

    def test_invalid_name_is_rejected(self) -> None:
        resource = create_resource("Laptop", created_at=CREATED)
        with pytest.raises(ResourceError, match="non-empty"):
            revise_resource(resource, name="  ", updated_at=REVISED)

    def test_rejects_non_resource(self) -> None:
        with pytest.raises(TypeError, match="resource must be a Resource"):
            revise_resource("resource", updated_at=REVISED)  # type: ignore[arg-type]


class TestUseResources:
    def test_links_resources(self, plan) -> None:
        task = create_task(plan, "Edit video", created_at=CREATED)
        camera = create_resource("Camera", created_at=CREATED)
        linked = use_resources(task, (camera,), updated_at=REVISED)
        assert linked.resource_ids == frozenset({camera.resource_id})
        assert linked.updated_at == REVISED

    def test_task_may_require_multiple_resources(self, plan) -> None:
        task = create_task(plan, "Edit video", created_at=CREATED)
        camera = create_resource("Camera", created_at=CREATED)
        studio = create_resource("Studio", created_at=CREATED)
        linked = use_resources(task, (camera, studio), updated_at=REVISED)
        assert linked.resource_ids == frozenset(
            {camera.resource_id, studio.resource_id}
        )

    def test_linking_is_idempotent(self, plan) -> None:
        task = create_task(plan, "Edit video", created_at=CREATED)
        camera = create_resource("Camera", created_at=CREATED)
        once = use_resources(task, (camera,), updated_at=REVISED)
        twice = use_resources(once, (camera,), updated_at=REVISED)
        assert twice.resource_ids == once.resource_ids

    def test_links_across_plans_are_allowed(self, plan) -> None:
        # Resources are user-level context, not plan-scoped (docs/03
        # states only "Task N:M Resources").
        other_plan = create_plan(
            create_goal(uuid.uuid4(), "Other", created_at=CREATED),
            HOUR,
            created_at=CREATED,
        )
        camera = create_resource("Camera", created_at=CREATED)
        here = use_resources(
            create_task(plan, "A", created_at=CREATED), (camera,), updated_at=REVISED
        )
        there = use_resources(
            create_task(other_plan, "B", created_at=CREATED),
            (camera,),
            updated_at=REVISED,
        )
        assert camera.resource_id in here.resource_ids
        assert camera.resource_id in there.resource_ids

    def test_link_carries_identity(self, plan) -> None:
        task = create_task(plan, "Edit video", created_at=CREATED)
        camera = create_resource("Camera", created_at=CREATED)
        linked = use_resources(task, (camera,), updated_at=REVISED)
        assert linked.task_id == task.task_id
        assert linked.plan_id == task.plan_id
        assert linked.created_at == task.created_at
        assert linked.title == task.title

    def test_empty_tuple_changes_only_the_stamp(self, plan) -> None:
        task = create_task(plan, "Edit video", created_at=CREATED)
        linked = use_resources(task, (), updated_at=REVISED)
        assert linked.resource_ids == frozenset()
        assert linked.updated_at == REVISED

    def test_non_tuple_resources_are_rejected(self, plan) -> None:
        task = create_task(plan, "Edit video", created_at=CREATED)
        camera = create_resource("Camera", created_at=CREATED)
        with pytest.raises(ResourceError, match="resources must be"):
            use_resources(
                task, [camera], updated_at=REVISED  # type: ignore[arg-type]
            )

    def test_rejects_non_task(self) -> None:
        camera = create_resource("Camera", created_at=CREATED)
        with pytest.raises(TypeError, match="task must be a Task"):
            use_resources(
                "task", (camera,), updated_at=REVISED  # type: ignore[arg-type]
            )


class TestTaskResourceIds:
    def test_task_starts_without_resources(self, plan) -> None:
        task = create_task(plan, "Title", created_at=CREATED)
        assert task.resource_ids == frozenset()

    def test_non_uuid_resource_ids_are_rejected(self, plan) -> None:
        task = create_task(plan, "Title", created_at=CREATED)
        with pytest.raises(Exception, match="resource_ids must contain UUIDs"):
            Task(
                task_id=task.task_id,
                plan_id=task.plan_id,
                title="Title",
                resource_ids=frozenset({"resource"}),  # type: ignore[arg-type]
            )

    def test_revision_carries_resource_links(self, plan) -> None:
        from backcasting.domain.task import revise_task

        task = create_task(plan, "Edit video", created_at=CREATED)
        camera = create_resource("Camera", created_at=CREATED)
        linked = use_resources(task, (camera,), updated_at=REVISED)
        revised = revise_task(linked, title="Edit the launch video", updated_at=REVISED)
        assert revised.resource_ids == frozenset({camera.resource_id})
