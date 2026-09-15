"""Resource domain model.

A Resource is anything a task needs beyond the actor's own time —
a tool, a venue, a piece of equipment. Resources are one of the
backcasting inputs (docs/04) and part of the shared planning
context (docs/02); docs/03 links them to work with a single
relationship, "Task N:M Resources", and imposes no ownership or
scoping rule — so a Resource is a standalone catalog entity: any
task may require any resource, and the N:M link carries no data
beyond membership.

When a required resource cannot be provided, scheduling fails with
``RESOURCE_UNAVAILABLE`` (docs/06) — the failure reason belongs to
the scheduling epic; this module only records the requirement
(:func:`use_resources` writes the link into the Task's
``resource_ids``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime

from backcasting.domain.task import Task
from backcasting.domain.timezone import UTC, require_utc

MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000


class ResourceError(ValueError):
    """Raised when a resource invariant is violated."""


@dataclass(frozen=True)
class Resource:
    """A shareable thing a task may require."""

    resource_id: uuid.UUID
    name: str
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.resource_id, uuid.UUID):
            raise ResourceError("resource_id must be a UUID")
        name = self.name
        if not isinstance(name, str) or not name.strip():
            raise ResourceError("name must be a non-empty string")
        if len(name.strip()) > MAX_NAME_LENGTH:
            raise ResourceError(f"name must be at most {MAX_NAME_LENGTH} characters")
        object.__setattr__(self, "name", name.strip())
        description = self.description
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise ResourceError("description must be a string")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise ResourceError(
                f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        object.__setattr__(self, "description", description)
        for stamp_name in ("created_at", "updated_at"):
            stamp = getattr(self, stamp_name)
            require_utc(stamp_name, stamp, error=ResourceError)
        if self.updated_at < self.created_at:
            raise ResourceError("updated_at must not precede created_at")


def create_resource(
    name: str,
    *,
    description: str = "",
    resource_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Resource:
    """Create a standalone Resource.

    Resources are catalog entities: they carry no plan or calendar
    scope (docs/03 states only "Task N:M Resources"), so creation
    needs nothing but a name.
    """
    now = created_at if created_at is not None else datetime.now(UTC)
    return Resource(
        resource_id=resource_id if resource_id is not None else uuid.uuid4(),
        name=name,
        description=description,
        created_at=now,
        updated_at=now,
    )


def revise_resource(
    resource: Resource,
    *,
    updated_at: datetime,
    name: str | None = None,
    description: str | None = None,
) -> Resource:
    """Return a revised copy of ``resource`` with ``updated_at`` advanced.

    The Resource's identity and ``created_at`` are carried over
    unchanged; passing ``None`` for a field keeps it.
    """
    if not isinstance(resource, Resource):
        raise TypeError("resource must be a Resource")
    return replace(
        resource,
        name=name if name is not None else resource.name,
        description=(
            description if description is not None else resource.description
        ),
        updated_at=updated_at,
    )


def use_resources(
    task: Task,
    resources: tuple[Resource, ...],
    *,
    updated_at: datetime,
) -> Task:
    """Return ``task`` extended to require ``resources`` (Task N:M Resources).

    The link set is a union on the Task's ``resource_ids``, so
    re-requiring an already-linked resource is idempotent. Resources
    are not plan-scoped — a task may require any resource — so the
    only failure is a type error.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    if not isinstance(resources, tuple):
        raise ResourceError("resources must be a tuple of Resource")
    for resource in resources:
        if not isinstance(resource, Resource):
            raise ResourceError("resources must be Resource instances")
    linked = task.resource_ids | {resource.resource_id for resource in resources}
    return replace(task, resource_ids=frozenset(linked), updated_at=updated_at)
