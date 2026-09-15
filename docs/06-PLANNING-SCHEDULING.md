# Planning & Scheduling

## Planning
Defines what must happen and the workload required.

## Scheduling
Places schedulable tasks into feasible time slots.

## Rolling Horizon
Long-term: milestones/approximate allocation.
Short-term: exact tasks and slots.
Default operational horizon: next 2 weeks.

## Failure Reasons
NO_CAPACITY, NO_AVAILABLE_SLOT, HARD_CONSTRAINT, DEPENDENCY_BLOCKED, DEADLINE_CONFLICT, RESOURCE_UNAVAILABLE.

## Principle
Conflict should first be resolved through rescheduling; escalate to replanning only when Plan-level feasibility is affected.
