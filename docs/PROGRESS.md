# Project Progress

## Current
- Phase: Implementation
- Current Task: TASK-013 (Current State)
- Current Epic: EPIC-002 Core Domain

## Completed
- Product/domain design baseline completed before implementation pack generation.
- TASK-001 — Repository bootstrap (2026-09-15): committed the execution pack, materialized the
  monorepo skeleton (`apps/api`, `apps/web`, `packages/contracts`, `infra`, `scripts`, `tests`),
  added the root pytest harness and repository-structure invariant tests (48 tests, all passing).
- TASK-002 — AGENTS.md enforcement (2026-09-15): added `scripts/check_rules.py`
  enforcing machine-checkable AGENTS.md rules (AGENTS.md section integrity, no tracked
  secret files, placeholder-only `.env.example` credentials, domain-layer import purity
  under `apps/api`) with 21 enforcement tests including fixture-based detection cases.
- TASK-003 — PROJECT_STATE foundation (2026-09-15): added `scripts/project_state.py`
  validating PROJECT_STATE.json (schema, lifecycle enums, validation results, ISO dates)
  and cross-checking it against tasks/TASK-MANIFEST.json and task-file statuses
  (current task exists and is not already COMPLETED, dependencies completed before a
  task becomes current, last completed task really marked COMPLETED). Resolved spec
  conflict: stale "verified by TASK-003" references corrected to TASK-009 (see
  SESSION-LOG).
- TASK-004 — Progress system foundation (2026-09-15): added `scripts/progress.py`
  with a backlog `report` command (per-epic status aggregation from the task
  manifest and task files) and a `check` command detecting drift between
  docs/PROGRESS.md and PROJECT_STATE.json (current task/epic identifiers,
  required sections, SESSION-LOG presence). 15 tests covering aggregation,
  unknown-status handling, and drift detection.
- TASK-005 — Git workflow foundation (2026-09-15): added `scripts/git_workflow.py`
  enforcing AGENTS.md §9 statically — `check-branch` rejects protected branches and
  malformed task-branch names (feature|fix|chore|docs/TASK-###-short-name);
  `check-commits` requires Conventional Commit style for non-merge commits on a
  branch. 33 tests against temporary git repositories.
- TASK-006 — CI baseline (2026-09-15): added `.github/workflows/ci.yml` running
  pytest plus all repository validators (check_rules, project_state, progress,
  conventional commits on PRs) on pushes and PRs to main, with
  `requirements-dev.txt` for dev dependencies (unpinned until TASK-009).
  6 workflow-structure tests.
- TASK-007 — Docker baseline (2026-09-15): added `infra/docker-compose.yml` with
  PostgreSQL 18 and Redis (health checks, persistent volume, credential placeholders
  via env vars). Live smoke test passed (both services healthy). Bug found and fixed:
  PostgreSQL 18 rejects a volume mounted directly at the data directory; the mount
  must be at `/var/lib/postgresql` (regression test added). 7 tests.
- TASK-008 — Environment configuration (2026-09-15): first backend code —
  `apps/api/src/backcasting/config.py`, a stdlib-only validated `Settings` layer
  (APP_ENV/LOG_LEVEL enums, PostgreSQL DATABASE_URL and redis:// REDIS_URL schemes,
  JWT_SECRET required and placeholder-rejected with a 32-char minimum in production,
  LLM provider allowlist with model-requires-provider). Optional `.env` seeding with
  real-environment precedence. 22 tests via a root `tests/conftest.py` path shim.
- TASK-009 — Technology verification (2026-09-15): verified exact versions against
  official sources (PyPI, npm registry, nodejs.org, Docker Hub) and recorded them in
  `docs/adr/ADR-007-technology-versions.md` with rationale, security notes, and
  breaking-change posture. Backend deps exactly pinned in `apps/api/pyproject.toml`
  (fastapi 0.141.1, uvicorn 0.53.0, sqlalchemy 2.0.53, alembic 1.20.0, psycopg 3.3.5,
  redis 8.1.0); compose images pinned (postgres:18.4, redis:7.4.11-alpine, live smoke
  test passed); requirements-dev pinned. TypeScript deliberately 5.9.3 (not 7.0.2);
  worker framework deliberately deferred. 11 traceability tests enforce pin/ADR sync.
- TASK-010 — Shared contracts foundation (2026-09-15): ADR-008 — the FastAPI app is
  the single source of truth for the API contract. Added `backcasting.app.create_app()`
  (application factory with `GET /health`) and `scripts/generate_contracts.py`, which
  exports the OpenAPI schema to `packages/contracts/openapi.json` (committed) with a
  `--check` drift mode wired into CI. Discovered starlette 1.6 deprecates httpx for
  TestClient — switched the test client dependency to httpx2 2.13.0 (ADR-007 updated).
  6 tests (app metadata, health, contract validity/identity/drift). EPIC-001 complete.
- TASK-011 — User model (2026-09-15): first domain entity —
  `apps/api/src/backcasting/domain/user.py` with the `Email` value object
  (validated, domain-lowercased) and the frozen `User` entity (UUID identity,
  IANA timezone via ZoneInfo, non-empty ≤100-char display name, timezone-aware
  UTC `created_at`), plus a `create_user` factory with injectable
  id/timestamp for deterministic tests. Added `tzdata==2026.4` as a runtime
  dependency (zoneinfo has no system tz database on Windows; ADR-007 updated).
  35 tests. EPIC-002 started.
- TASK-012 — Goal model (2026-09-15): `apps/api/src/backcasting/domain/goal.py`
  with the frozen `Goal` entity (UUID identity + owning `user_id` per
  "User 1:N Goals", stripped non-empty title ≤200, optional description
  ≤2000, timezone-aware UTC created/updated with updated ≥ created) and
  `GoalStatus` covering exactly the spec's six lifecycle states
  (DRAFT → ACTIVE → PAUSED → COMPLETED/CANCELLED/ARCHIVED). New goals start
  in DRAFT; `create_goal`/`revise_goal` factories with injectable id/clock.
  Transition rules deliberately deferred to the goal-lifecycle task.
  22 tests.

## Notes
- This file is historical. Keep the current state in `PROJECT_STATE.json`.
