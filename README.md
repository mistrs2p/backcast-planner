# Backcasting Goal & Adaptive Planning System

An adaptive planning system that starts from a desired future state, backcasts toward the present, converts the path into milestones/outcomes/tasks, schedules work against real calendar and capacity constraints, measures execution, and replans when reality diverges from the plan.

## Execution Model

`Goal → Future State → Backcasting → Strategy → Plan → Tasks → Schedule → Execute → Measure → Replan`

## First Run

1. Read `AGENTS.md`.
2. Read `PROJECT_STATE.json`.
3. Start with `tasks/EPIC-001-foundation/TASK-001-repository-bootstrap.md`.
4. Follow dependencies and Definition of Done.
5. Keep project state and docs synchronized.

## Repository Memory

- `PROJECT_STATE.json`: compact current state.
- `docs/PROGRESS.md`: historical progress.
- `docs/SESSION-LOG.md`: notable session discoveries.
- `docs/adr/`: architectural decisions.
- `tasks/`: executable backlog and task contracts.

## Repository Layout

```text
apps/api/            FastAPI backend (modular monolith)
apps/web/            Next.js + TypeScript + Tailwind frontend
packages/contracts/  Shared API contracts
infra/               Infrastructure definitions (Docker-first)
scripts/             Development and validation scripts
tests/               Repository-level test suite
docs/                Specifications, ADRs, progress and session logs
tasks/               Executable backlog (epics → tasks)
```

## Core Technology Baseline

- Next.js 16.x + TypeScript
- Tailwind CSS 4.x
- FastAPI 0.141.x + Python
- PostgreSQL 18.x
- SQLAlchemy 2.x + Alembic
- Docker-first local development
- Redis + worker for asynchronous work when justified

Exact dependency versions must be verified by `TASK-009` against official release documentation before lockfiles are finalized.
