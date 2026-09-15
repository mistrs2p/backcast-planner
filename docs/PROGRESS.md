# Project Progress

## Current
- Phase: Implementation
- Current Task: TASK-031 (Recurrence rules)
- Current Epic: EPIC-004 Calendar

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
- TASK-013 — Current State (2026-09-15): immutable snapshot of present
  reality per goal — `apps/api/src/backcasting/domain/current_state.py` with
  the frozen `CurrentState` entity (UUID identity, goal reference,
  non-empty stripped narrative ≤5000, timezone-aware UTC `captured_at`) and
  `capture_current_state` factory. Snapshots accumulate rather than mutate,
  matching the replanning model's "new Current State" re-run. 13 tests.
- TASK-014 — Future State (2026-09-15): destination state a Goal backcasts
  from — `apps/api/src/backcasting/domain/future_state.py` with the frozen
  `FutureState` entity (UUID identity, goal reference — 1:1 in MVP enforced
  at the repository layer, non-empty description ≤5000, UTC-aware
  `target_date` strictly after `created_at`) and the
  `define_future_state`/`revise_future_state` factories. Design decision
  within spec latitude: the time anchor (target date) lives on the Future
  State, not the Goal, so replanning preserves the destination exactly as
  docs/08 requires while Goal Revision is the only sanctioned mutation.
  20 tests.
- TASK-015 — Metric abstraction (2026-09-15):
  `apps/api/src/backcasting/domain/metric.py` implementing docs/07's
  measurement requirements — `MetricKind` (count/duration/percentage/
  boolean/score with per-kind value validation; composite metrics noted as
  future work per spec), `MetricDirection` (maximize/minimize/target),
  the `Metric` definition (target direction requires a target value, score
  kind requires an explicit min<max scale, `False` is a valid boolean
  target), and `interpret_variance` producing a `Variance` with the
  actual−planned delta and direction-aware favourability. 54 tests.
- TASK-016 — Goal lifecycle (2026-09-15): transition rules added to
  `domain/goal.py` — `GOAL_TRANSITIONS` (DRAFT→ACTIVE; ACTIVE and PAUSED →
  PAUSED/ACTIVE respectively or any terminal state; COMPLETED/CANCELLED/
  ARCHIVED terminal with no outgoing edges), `TERMINAL_GOAL_STATUSES`,
  `can_transition`/`is_terminal` inspection helpers, `transition_goal`
  (returns a new instance advancing `updated_at`, raises
  `InvalidGoalTransition` carrying from/to statuses). One inferred edge
  beyond the literal spec chain: PAUSED→ACTIVE resume, since a pause that
  could never resume would be indistinguishable from cancellation.
  47 tests.
- TASK-017 — Domain validation (2026-09-15): cross-entity validation seam
  per docs/09 / ADR-002 ("the Domain validates and enforces") —
  `domain/validation.py` with `ValidationIssue`, `validate_goal_context`
  (ownership matching for Future/Current State; target date must lie after
  the current-state snapshot), and `require_valid` aggregating all issues
  into a `DomainValidationError`. Entity-local invariants remain in their
  constructors; this layer sees what they cannot. 14 tests.
- TASK-018 — Domain events (2026-09-15): `domain/events.py` with the
  frozen `DomainEvent` envelope (typed via `DomainEventType`, UTC
  `occurred_at`, UUID identity, payload wrapped in a read-only
  `MappingProxyType` copy), the in-memory `EventCollector`, and
  constructors for the operations the core domain supports (goal
  created/revised/status-changed, current state captured, future state
  defined/revised). Persistence/publication deferred to infrastructure
  tasks, keeping the domain free of delivery mechanisms. 22 tests.
- TASK-019 — Repository interfaces (2026-09-15): the domain's persistence
  ports — `domain/repositories.py` with abstract `UserRepository`,
  `GoalRepository`, `CurrentStateRepository`, and `FutureStateRepository`
  (insert-or-replace `save` keyed by entity id, `None` for absence,
  ordering guarantees for list methods, `get_for_goal` for the MVP's 1:1
  destination, `RepositoryError` for infrastructure failures). Dependency
  direction points inward: infrastructure will implement these with
  SQLAlchemy; the domain imports nothing from it. Contract pinned by 23
  tests including in-memory fakes. EPIC-002 complete.
- TASK-020 — Gap model (2026-09-15): the shape of the "distance between
  present and destination" (docs/02, docs/04 step 4) —
  `domain/gap.py` with `GapDimension` (a metric plus validated
  current/target values) and the frozen `Gap` entity tying one current
  state snapshot to one future state for a goal, with an optional bounded
  narrative, unique metric names per gap, and a UTC `calculated_at`.
  Value derivation (the calculation itself) is the following task.
  21 tests. EPIC-003 started.
- TASK-021 — Gap calculation (2026-09-15): `calculate_gap` in
  `domain/gap.py` — the deterministic backcasting step 4. Validates the
  assembled context through TASK-017's cross-entity validator first (a gap
  is only recorded for a context that hangs together: matching ownership,
  target after snapshot), then builds `GapDimension`s from
  (metric, current, target) triples with per-metric validation and
  no duplicates, and records the gap with an injectable id/clock.
  13 tests.
- TASK-022 — Backcasting run (2026-09-15): `domain/backcasting_run.py` —
  the record of one pipeline execution per goal ("Goal 1:N Backcasting
  Runs"; replanning produces a new run). `BackcastingRun` ties the run to
  its exact inputs (goal, current state, future state, gap) with a
  RUNNING → COMPLETED/FAILED lifecycle completed exactly once
  (`completed_at` UTC ≥ `started_at`, coupled to terminal status).
  `start_run` guards context validity and gap provenance (the gap must be
  computed from exactly this snapshot and destination). Pipeline
  orchestration itself is the backcasting-integration task. 29 tests.
- TASK-023 — Strategy model (2026-09-15): the method of movement
  (docs/02; pipeline steps 8–9) — `domain/strategy.py` with the frozen
  `Strategy` entity (UUID identity, run + goal references, bounded
  name/rationale, UTC stamps) and a CANDIDATE → SELECTED/REJECTED
  one-shot lifecycle via `decide_strategy` (terminal statuses final,
  `InvalidStrategyTransition` on illegal moves). `propose_strategy`
  binds candidates to a RUNNING run only — strategies are generated
  during the pipeline. 29 tests.
- TASK-024 — Strategy generation (2026-09-15): the deterministic side of
  pipeline step 8 per docs/09 / ADR-002 ("the LLM proposes; the Domain
  validates and enforces") — `StrategyProposal` (validated raw proposal
  as an AI adapter emits it) and `accept_proposed_strategies`, which
  turns a proposal batch into run candidates only when the run is
  RUNNING, the batch is non-empty (empty generation is a failed step),
  and names are unique. 16 tests.
- TASK-025 — Feasibility engine (2026-09-15): `domain/feasibility.py`
  implementing the spec rule "Required Workload + Buffer ≤ usable
  Capacity" (docs/04, pipeline step 7) as a deterministic comparison of
  non-negative timedeltas — `evaluate_feasibility` returns a
  `FeasibilityResult` with `feasible` (boundary equality counts as
  feasible), `total_required`, and signed `slack`. Durations only; where
  capacity comes from is the calendar/capacity epics. 15 tests.
- TASK-026 — Milestone model (2026-09-15): the intermediate measurable
  checkpoint (docs/02, pipeline step 10) — `domain/milestone.py` with
  the frozen `Milestone` entity (UUID identity, run + goal references —
  the Plan 1:N Milestones link is established when the Plan model
  exists, bounded title/description, UTC `target_date` strictly after
  creation) and `define_milestone` bound to a RUNNING run. Design
  decision within spec latitude: a milestone carries no lifecycle of
  its own — as a *measurable* checkpoint its achievement is expressed
  through its Outcomes (Milestone 1:N Outcomes, docs/03) rather than a
  status flag. 28 tests.
- TASK-027 — Milestone generator (2026-09-15): the deterministic side of
  pipeline step 10 per docs/09 / ADR-002 — `MilestoneProposal` (validated
  raw proposal as an AI adapter emits it) and `accept_proposed_milestones`,
  which turns a proposal batch into run milestones only when the run is
  RUNNING against exactly that destination (state-id provenance), the
  batch is non-empty, titles are unique, target dates are strictly
  increasing, and every checkpoint lies strictly between acceptance and
  the destination's target date (intermediate — never the destination
  itself). 24 tests.
- TASK-028 — Backcasting integration (2026-09-15): `domain/backcasting.py`
  with `execute_backcasting`, the deterministic orchestration of EPIC-003's
  steps — calculate gap → start run → evaluate feasibility → accept
  proposed strategies → select the named candidate (others rejected) →
  accept proposed milestones → complete the run — returning a
  `BackcastingResult`. Steps 5–6 (time environment, workload) arrive as
  caller-supplied inputs until the calendar/capacity epics; steps 11–15
  are deferred to the planning epic. Failure semantics: the run starts
  before the first fallible step and ends exactly once — infeasibility
  raises `InfeasibleBackcasting` (carrying the FAILED run and the
  feasibility numbers) and any step failure raises `BackcastingStepError`
  (carrying the FAILED run and the step name). 18 tests. EPIC-003
  complete.
- TASK-029 — Calendar model (2026-09-15): first piece of EPIC-004 —
  `domain/calendar.py` with the frozen `Calendar` root (UUID identity,
  owning `user_id` per "Calendar belongs to User", a valid ZoneInfo home
  timezone anchoring all timezone-aware operations, UTC stamps) and
  `create_calendar`. The MVP planning granularity (15 minutes, docs/05)
  is pinned as the module constant `PLANNING_GRANULARITY` — an MVP-wide
  constant rather than per-calendar state. Events, recurrence,
  exceptions, availability, and floating rest follow in their tasks.
  15 tests. EPIC-004 started.
- TASK-030 — Calendar event (2026-09-15): `domain/calendar_event.py` with
  the frozen `CalendarEvent` (UUID identity, calendar reference, bounded
  title/description, UTC `start`/`end` with end > start) and
  `create_event` bound to a calendar. Design decisions within spec
  latitude: events are *not* forced onto the 15-minute planning
  granularity (that governs task placement; existing commitments arrive
  at reality's times) and an event carries no task link — "Calendar
  Event is not necessarily a Task" (docs/03). 29 tests.

## Notes
- This file is historical. Keep the current state in `PROJECT_STATE.json`.
