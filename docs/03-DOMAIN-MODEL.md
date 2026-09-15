# Domain Model

## Core Relationships
- User 1:N Goals
- Goal 1:1 Desired Future State in MVP
- Goal 1:N Backcasting Runs
- Goal 1:N Plans
- Goal max 1 Active Plan
- Plan 1:N Milestones
- Plan 1:N Outcomes
- Plan 1:N Tasks
- Milestone 1:N Outcomes
- Outcome N:M Tasks
- Task 1:N Schedules
- Task 1:N Executions
- Task N:M Resources
- User owns calendar, availability, preferences, constraints, habits and routines

## Lifecycle
Goal: DRAFT → ACTIVE → PAUSED → COMPLETED/CANCELLED/ARCHIVED.
Plan: DRAFT/CANDIDATE → ACTIVE → SUPERSEDED/ARCHIVED/INVALID.

## Key Rules
- No silent Goal change during replanning.
- Outcome may exist without Tasks.
- Task may serve multiple Outcomes.
- Calendar Event is not necessarily a Task.
- Schedule and Replanning are distinct.
