# Task System

## Lifecycle
DRAFT → READY → IN_PROGRESS → VALIDATING → COMPLETED

Possible interruption states: BLOCKED, FAILED, CANCELLED.

## Selection Rule
Choose the lowest-numbered READY task whose dependencies are complete, unless a later task is explicitly unblocked and the active task is blocked.

## Task Completion
Acceptance criteria, tests, lint/typecheck/build as applicable, docs/state updates, atomic commit, and push are required.
