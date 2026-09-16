# Project Progress

## Current
- Phase: Implementation
- Current Task: TASK-114 (Progress UI)
- Current Epic: EPIC-011 Product UX

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
- TASK-031 — Recurrence rules (2026-09-15): `domain/recurrence.py` with
  the frozen `RecurrenceRule` (DAILY/WEEKLY MVP frequencies, interval ≥ 1,
  optional weekday set for weekly rules, optional `until`, positive
  duration, event-template title/description) plus `occurrences` (pure
  start-instant computation over a window) and `expand_rule` (binds
  occurrences to a calendar as events). Expansion preserves the anchor's
  *local* time of day in the rule's zone — wall-clock semantics, so a
  9:00 London occurrence stays 9:00 across DST while its UTC instant
  shifts (ambiguous fall-back times resolve to fold=0). Exceptions that
  override individual occurrences are the next task. 36 tests.
- TASK-032 — Exceptions (2026-09-15): "recurring rules may have
  exceptions" (docs/05) — `domain/recurrence_exception.py` with the
  frozen `RecurrenceException` addressing an occurrence by its original
  start instant (CANCELLED drops it; RESCHEDULED moves it, optionally
  overriding duration), `cancel_occurrence`/`reschedule_occurrence`
  factories, and `expand_with_exceptions` applying a batch to a rule's
  expansion. Non-matching exceptions are ignored (windows clip
  occurrences); conflicting exceptions for the same instant are
  rejected. 32 tests.
- TASK-033 — Floating rest (2026-09-15): "floating rest supports quotas
  without fixed weekdays" (docs/05) — `domain/floating_rest.py` with the
  frozen `FloatingRest` weekly quota (positive timedelta bound to a
  calendar; the week is the accrual window since the spec contrasts
  floating rest with fixed weekdays) and `evaluate_rest`, which measures
  satisfaction from arbitrary rest intervals, merging overlapping and
  touching intervals so the same rest time is never counted twice
  (over-rest keeps `satisfied` true with negative `remaining`). Where
  rest is *placed* is the scheduler's concern. 32 tests.
- TASK-034 — Availability (2026-09-15): the Availability Window concept
  (docs/05) — `domain/availability.py` with the frozen
  `AvailabilityWindow` (non-empty weekday set, naive local wall-clock
  start/end within one day — no cross-midnight windows in MVP, a
  ZoneInfo anchor defaulting to the calendar's zone, optional title)
  and `available_intervals`, which expands the weekly pattern into UTC
  intervals over a range, preserving local times across DST and
  clipping to the range bounds. Availability ≠ capacity (docs/00):
  capacity is computed from these windows in the capacity epic.
  35 tests.
- TASK-035 — Timezone handling (2026-09-15): the single home for the
  mandatory timezone semantics (docs/05 "Timezone-aware operations are
  mandatory"; docs/10 "Persisted instants use UTC; user timezone is used
  for interpretation/display") — `domain/timezone.py` with
  `require_utc` (the shared UTC-instant check, error class injected so
  each module keeps its typed errors), `to_utc` (naive rejected, never
  guessed), `local_time`/`instant_from_wall_clock` (wall-clock
  semantics across DST, ambiguous times resolve to fold), and
  `local_time_kind` (UNAMBIGUOUS/AMBIGUOUS/NONEXISTENT via round-trip
  classification) plus `week_bounds` (Monday-anchored local week as UTC
  instants; DST weeks are correctly 167/169 hours). The four private
  `_require_utc` copies in recurrence, recurrence exception, floating
  rest, and availability were consolidated onto the shared helper.
  24 tests.
- TASK-036 — Calendar conflict detection (2026-09-15): the deterministic
  side of "conflict should first be resolved through rescheduling"
  (docs/06) — `domain/conflict.py` with `detect_conflicts`, a sweep
  over a calendar's events reporting each overlapping pair exactly
  once as a frozen `Conflict` carrying both events and the shared
  interval. Semantics: half-open intervals, so back-to-back events do
  not conflict; all events must belong to the one calendar; output is
  deterministic regardless of input order. Bug found and fixed (latent,
  never hit by existing tests): the `timezone` parameter of
  `create_calendar`, `create_rule`, and `create_availability_window`
  shadowed the `datetime.timezone` import, crashing the default clock
  with `AttributeError` whenever `created_at` was omitted — the three
  factories now use the shared `UTC` constant, with regression tests
  in each module. Resolution (rescheduling/replanning escalation) is
  the planning epic's concern. 20 tests (+3 regression).
- TASK-037 — Calendar API (2026-09-15): the layered architecture
  materializes (docs/10 Presentation → Application → Domain →
  Infrastructure) — `CalendarRepository`/`CalendarEventRepository`
  ports added to the domain ("User owns calendar" read as 1:1 in the
  MVP: `get_by_user` returns the user's single calendar);
  `application/calendars.py` with `CalendarService` composing the
  calendar use cases (create calendar, place event with UTC
  normalization per the persistence rule, list events, detect
  conflicts) and application-level errors (not-found, one-per-user,
  invalid timezone); `infrastructure/memory.py` with thread-safe
  in-memory repository implementations until the production
  persistence epic; `api/calendars.py` exposing
  POST/GET /calendars, POST/GET /calendars/{id}/events, and
  GET /calendars/{id}/conflicts with the status mapping 404 unknown
  calendar / 409 second calendar / 422 domain violations. `create_app`
  gained injectable repositories (in-memory defaults); the OpenAPI
  contract regenerated (ADR-008). 40 tests. EPIC-004 complete.
- TASK-038 — Planned capacity (2026-09-15): EPIC-005 started — the
  forward-looking answer to "Availability ≠ Capacity" (docs/00) —
  `domain/planned_capacity.py` with the frozen `PlannedCapacity`
  record (calendar, UTC period bounds, non-negative amount) and
  `derive_planned_capacity`: the deterministic computation merging a
  calendar's availability windows over a period (TASK-034 wall-clock
  semantics, clipped to the period) and subtracting the existing
  commitments *occupying* them — overlapping windows and events are
  merged first so no time is double-counted, and commitments outside
  the windows consume none of the workable time. Design decision
  within spec latitude: commitments reduce planned capacity where they
  overlap availability (a meeting at 22:00 doesn't eat an 18–21
  window); what actually happened is Observed Capacity (next task).
  33 tests.
- TASK-039 — Observed capacity (2026-09-15): the backward-looking
  measurement ("Measurement: observed data", docs/02) —
  `domain/observed_capacity.py` with the frozen `ObservedCapacity`
  record and `measure_observed_capacity`, running the *same* semantics
  as planned capacity (extracted into the shared `workable_time`
  helper in `domain/planned_capacity.py`) over a period that has
  happened. Two invariants distinguish a measurement from an estimate:
  a period can only be measured after it ends
  (`measured_at ≥ period_end`), and a measurement is an immutable
  historical fact — no `updated_at`, no revision path; a corrected
  measurement is a new record. This planned/observed contrast is what
  makes capacity variance (docs/07) meaningful. 24 tests.
- TASK-040 — Effective capacity (2026-09-15): the *usable* capacity
  the feasibility rule trusts (docs/04 step 7 "Required Workload +
  Buffer ≤ usable Capacity") — `domain/effective_capacity.py` with the
  frozen `EffectiveCapacity` record (amount plus the planned/observed
  totals and sample count it derives from), `CapacitySample` (pairing
  one past period's planned and observed records — same calendar, same
  period), and `compute_effective_capacity`: no history → the plan is
  trusted (cold start); zero total planned across history → the ratio
  is undefined, plan trusted; otherwise the plan scaled by the
  aggregate Σobserved/Σplanned ratio. Design decision within spec
  latitude: the result is *not* capped at the plan — over-delivery is
  real signal, and conservatism is the buffer's job (its own task).
  24 tests.
- TASK-041 — Capacity pool (2026-09-15): splitting a period's usable
  capacity across a user's competing goals —
  `domain/capacity_pool.py` with the frozen `CapacityAllocation`
  (goal + non-negative amount; zero holds a place without consuming
  capacity) and `CapacityPool` (the split of an effective-capacity
  record: unique goals, `allocated_amount` equals the allocation sum,
  `unallocated_amount` is the non-negative remainder the scheduler may
  still commit), plus `allocate_capacity` and the `allocation_for`
  lookup. 23 tests.
- TASK-042 — Constraints (2026-09-15): the hard restrictions the
  scheduler must never violate (docs/05 hierarchy, docs/13 "Hard
  constraints are never violated", the `HARD_CONSTRAINT` failure
  reason in docs/06) — `domain/constraint.py` with the frozen
  `Constraint` in two MVP kinds: `BLOCKED_RANGE` (a fixed UTC interval
  nothing may be scheduled in) and `BLOCKED_WEEKLY` (a weekly
  wall-clock exclusion anchored to a timezone — the mirror image of an
  Availability Window, DST-aware, no cross-midnight blocks), plus the
  factories, `blocked_intervals` (expansion into UTC intervals over a
  range, clipped, chronological) and `is_blocked` (half-open overlap
  check: scheduling to end exactly as a block begins is allowed).
  33 tests.
- TASK-043 — Preferences (2026-09-15): the soft layer of the
  scheduling hierarchy ("… → capacity → soft preferences →
  optimization", docs/05) — advisory guidance the optimizer ranks
  candidates by but may violate, in explicit contrast with hard
  constraints (docs/13) — `domain/preference.py` with the frozen
  `Preference`: a weekly wall-clock window (the same shape as an
  Availability Window: naive local times, no cross-midnight,
  ZoneInfo-anchored, defaulting to the calendar's zone) with a
  direction (`PREFER` — slots inside are better; `AVOID` — worse) and
  an integer `weight` 1–5, plus `create_preference`,
  `preference_windows` (DST-aware UTC expansion, clipped,
  chronological) and `applies_to` (half-open touch check returning a
  bool — a preference never rejects a slot, it only reports
  applicability). 32 tests.
- TASK-044 — Buffer (2026-09-15): the conservatism layer of the
  feasibility rule "Required Workload + Buffer ≤ usable Capacity"
  (docs/04) — `domain/buffer.py` with the frozen `Buffer`: a
  per-period policy reserving a `ratio` fraction of usable capacity
  (0 ≤ ratio < 1 — a full reserve is abstention, not a buffer;
  finite, non-bool), plus `create_buffer`, `reserved_amount` /
  `usable_amount` (ratio application, rounding clamped at zero) and
  `apply_buffer`, which pairs a buffer with the `EffectiveCapacity`
  record of the same calendar and period and yields the
  `BufferedCapacity` (reserved + usable, never negative) the
  feasibility rule consumes. Completes the split of labor fixed in
  TASK-040: effective capacity may exceed the plan when history
  over-delivers; conservatism lives here. 32 tests.
- TASK-045 — Capacity analysis (2026-09-15): pipeline step 5
  "Analyze time environment" (docs/04) — `domain/capacity_analysis.py`
  with `analyze_time_environment`, the deterministic composition of
  the epic's chain: merged availability windows → hard-constraint
  blocks (constraints remove availability the way commitments do) →
  occupying commitments (only the part landing on available time
  consumes capacity) → planned → effective (history-adjusted via
  `compute_effective_capacity`) → usable (buffer reserve via
  `apply_buffer`), returning the frozen `CapacityAnalysis` record
  (availability/commitment/constrained/occupying/planned/effective/
  reserved/usable amounts, sample count, buffer ratio). The analysis's
  `usable_amount` is exactly the `usable_capacity` input
  `execute_backcasting` expects — the step-5 output now has a
  producer. Design decisions within spec latitude: preferences are
  deliberately absent (the soft layer ranks slots, it never reduces
  capacity); constraint-blocked availability is subtracted at this
  analysis level while `derive_planned_capacity` keeps its TASK-038
  record semantics (availability − occupying commitments). 27 tests.
- TASK-046 — Capacity integration tests (2026-09-15): the epic-closing
  integration suite `tests/test_capacity_integration.py` wiring
  EPIC-004's calendar machinery (weekly recurrence with cancelled and
  rescheduled occurrences) into EPIC-005's capacity chain and on into
  the EPIC-003 pipeline: a realistic week analyzed end to end
  (40h availability, hard-blocked hours, standup commitments, a
  history sample measured with `measure_observed_capacity`, a 10%
  buffer) whose `usable_amount`/`reserved_amount` feed
  `execute_backcasting` to a COMPLETED run — and, overcommitted, to
  `InfeasibleBackcasting` carrying the FAILED run; exceptions proven
  to change capacity (a cancelled occurrence frees 30 minutes, a
  rescheduled one moves its bite out of the windows); the capacity
  pool splitting the analysis's effective amount across goals; the
  2026-03-29 London spring-forward proven to cost a real capacity
  hour through the whole chain; and the analysis's planned amount
  cross-checked against `workable_time`/`derive_planned_capacity`.
  8 tests. EPIC-005 complete.
- TASK-047 — Plan model (2026-09-15): first piece of EPIC-006 —
  `domain/plan.py` with the frozen `Plan`: the executable shape of a
  goal ("what must happen and the workload required", docs/06), owned
  by the goal (Goal 1:N Plans, docs/03), carrying the total
  `workload` (non-negative timedelta), optional `run_id` provenance
  (the backcasting run it was born from — a plan may also be authored
  directly), and the spec lifecycle
  DRAFT/CANDIDATE → ACTIVE → SUPERSEDED/ARCHIVED/INVALID via the
  `PLAN_TRANSITIONS` table (only a CANDIDATE may go ACTIVE; only an
  ACTIVE plan may be SUPERSEDED or INVALID — replacement happens to
  plans that were once in force; pre-active states may be ARCHIVED).
  `revise_plan` moves title/workload without touching identity or
  status (plans are adaptive, docs/00); `active_plan` reads back the
  single ACTIVE plan of a goal and raises on the corrupted
  more-than-one state ("Goal max 1 Active Plan", docs/03). 33 tests.
  EPIC-006 started.
- TASK-048 — Plan versioning (2026-09-15): the traceable replan
  history — "Every meaningful replan produces a traceable plan
  version with reason, source run and change set" (docs/08) —
  `domain/plan_version.py` with the frozen `PlanVersion` (per-plan
  strictly increasing version numbers, stripped non-empty reason
  ≤ 500, optional `source_run_id` provenance, immutable
  `PlanChangeSet` of the content fields a replan may move:
  title/workload) and `apply_plan_version`, which returns the next
  Plan value plus its version record — rejecting no-op change sets (a
  version must be a *meaningful* replan), foreign histories, and
  duplicate version numbers. `latest_version` reads the trail's head,
  order-independently. Design decisions within spec latitude:
  versions are append-only history, not state (the Plan value holds
  the current state); lifecycle moves are excluded from change sets —
  they flow through `transition_plan` with their own rules. 25 tests.
- TASK-049 — Outcome model (2026-09-15): the "achieved state/result"
  (docs/02, Planning Layer) — `domain/outcome.py` with the frozen
  `Outcome`: plan-owned (Plan 1:N Outcomes, docs/03), optionally
  bound to one milestone (Milestone 1:N Outcomes — a plan-level
  outcome without a milestone is legitimate: milestones are
  checkpoints, not the only way to state what "done" means),
  non-empty stripped title ≤ 200, description ≤ 5000. "Outcome may
  exist without Tasks" (docs/03) is honored structurally: no task
  reference lives here; the N:M link arrives with the task model. Like
  a milestone, an outcome carries no lifecycle of its own —
  achievement is measured (progress epic), not flagged.
  `revise_outcome` moves descriptive fields only; re-binding to
  another milestone is a different outcome, not a revision. 17 tests.
- TASK-050 — Task model (2026-09-15): the "actionable unit of work"
  (docs/02, Execution Layer) — `domain/task.py` with the frozen
  `Task`: plan-owned (Plan 1:N Tasks, docs/03), optional strictly
  positive `duration` (the estimated time to execute — absent until
  estimated, and `is_schedulable` is False until it lands), optional
  UTC `deadline` strictly after creation (the deadline layer of the
  docs/05 scheduling hierarchy), and `outcome_ids` — the Outcome N:M
  Tasks link, established by `serve_outcomes`, which keeps the link
  inside one plan and is idempotent ("Task may serve multiple
  Outcomes", docs/03). Schedules, executions, and resources stay out
  (each their own task/epic); "Calendar Event is not necessarily a
  Task" is honored by separation — a schedule places a task, it does
  not turn it into an event. `revise_task` moves editable fields;
  passing None keeps them. 29 tests.
- TASK-051 — Task dependencies (2026-09-15): the ordering layer of
  the docs/05 scheduling hierarchy ("… existing commitments →
  dependencies → …"; an unmet dependency is `DEPENDENCY_BLOCKED`,
  docs/06) — `domain/task_dependency.py` with the frozen
  `TaskDependency` finish-to-start link (the MVP relation: a task
  cannot start until the tasks it depends on have finished).
  Collections grow only through `add_dependency`, which rejects
  self-links, duplicates, cross-plan links, and the edge that closes
  a cycle (checked at write time, so valid collections are acyclic by
  construction; `topological_order` still checks defensively).
  `depends_on`/`blocks` give direct neighbors, `all_prerequisites`
  the transitive closure, and `topological_order` (Kahn's, stable on
  input order) the scheduler's deterministic processing order.
  Collections are plan-scoped by construction — persistence scoping is
  the repository's concern (EPIC-008). 25 tests.
- TASK-052 — Resources (2026-09-15): the "Task N:M Resources" link
  (docs/03) — `domain/resource.py` with the frozen `Resource`: a
  standalone catalog entity (name, description, stamps) with no plan
  or calendar scope, because docs/03 states only the N:M link and
  imposes no ownership rule; a resource is shared context, an input
  to backcasting (docs/04). `use_resources` writes the requirement
  into the Task's new `resource_ids` (a frozenset union, idempotent,
  mirroring `serve_outcomes`); tasks from any plan may require the
  same resource. `RESOURCE_UNAVAILABLE` (docs/06) stays with the
  scheduling epic — this module only records the requirement.
  25 tests.
- TASK-053 — Task estimation (2026-09-15): the task-level half of
  pipeline step 6, "Estimate workload" (docs/04) —
  `domain/task_estimation.py` with the frozen `TaskEstimation`: an
  append-only estimate record carrying duration, provenance
  (`EstimationSource` MANUAL/AI, per ADR-002's
  propose-then-validate split), and a rationale ≤500 chars.
  `apply_estimation` moves a record's duration onto its task (and
  only its task — foreign estimates are rejected), making it
  schedulable; `latest_estimation` resolves the current estimate
  from history (re-estimation appends, ties break toward the later
  position); `estimate_workload` sums a plan's task durations and
  refuses to sum silently over unestimated tasks — a missing
  estimate is surfaced, never hidden as a zero. The estimate
  records themselves are pure history; persistence is EPIC-008.
  29 tests.
- TASK-054 — Task decomposition contract (2026-09-15): pipeline
  step 12, "Generate tasks" (docs/04), behind ADR-002's split —
  `TaskProposal` (in `domain/task.py`) is the raw shape an AI
  adapter emits: title, description, optional duration/deadline,
  and outcome bindings referenced by title (ids are the domain's
  to assign). `accept_proposed_tasks` enforces the deterministic
  rules: the plan must not be terminal (SUPERSEDED/ARCHIVED/INVALID
  plans cannot gain tasks), supplied outcomes must belong to the
  plan and carry unique titles (a title reference must resolve to
  exactly one outcome), at least one proposal is required (empty
  generation is a failed step, mirroring milestones), task titles
  are unique within the batch, and every outcome reference must
  resolve — an unresolved reference is a contract violation, never
  a silently dropped link. Mirrors the MilestoneProposal/
  accept_proposed_milestones precedent. 21 tests.
- TASK-055 — Plan generation (2026-09-15): the assembly half of the
  pipeline tail (docs/04) — `domain/plan_generation.py`.
  `begin_plan` opens a DRAFT plan from a COMPLETED run (a running or
  failed run cannot birth a plan) with `run_id` provenance that
  docs/08 plan versioning reads back as `source_run_id`.
  `publish_plan` closes the draft into a CANDIDATE — the lifecycle's
  staging state before validation (TASK-056) can promote it to
  ACTIVE — stamping the workload as the computed sum of the tasks'
  estimates (`estimate_workload`; a `TaskEstimationError` propagates
  rather than being masked). Publishing requires the plan still be a
  DRAFT, every task belong to it, and at least one task exist: a
  plan with nothing to execute is not a plan, while outcomes without
  tasks remain outcome-level state (docs/03). `generate_plan`
  composes accept-proposals + publish over a begun draft; per
  ADR-002 nothing here generates content. 16 tests.
- TASK-056 — Plan validation (2026-09-15): pipeline step 14,
  "Validate" (docs/04) — `domain/plan_validation.py`, in the
  return-all-issues style of `domain/validation.py`.
  `validate_plan` checks the plan as a whole: task ownership
  (`task_owner_mismatch`), non-emptiness (`empty_plan`), full
  estimation (`unestimated_task`), workload drift
  (`workload_mismatch` — the recorded workload must equal the sum of
  the tasks' estimates), dependency health
  (`dependency_reference_outside`/`dependency_cycle` via
  `topological_order`), and the spec feasibility rule `infeasible`
  (workload + buffer ≤ usable capacity, docs/04).
  `activate_plan` applies the promotion gate: only a CANDIDATE may
  activate, and "Goal max 1 Active Plan" (docs/03) holds — a
  competing active plan must be superseded or archived first. A
  failed validation leaves the candidate a candidate: the domain
  reports, it does not destroy. 23 tests. EPIC-006 complete.
- TASK-057 — Candidate slot generation (2026-09-15): first piece of
  EPIC-007, the raw material of scheduling ("places schedulable
  tasks into feasible time slots", docs/06) —
  `domain/candidate_slot.py` with the frozen `CandidateSlot` (a
  maximal free UTC interval, `can_fit` for placement checks).
  `generate_candidate_slots` mirrors `workable_time`'s semantics
  exactly — merged availability minus occupying commitments, clipped
  to the horizon, touching intervals merged so no time is offered
  twice, in-window-only commitment consumption, DST-safe expansion —
  and keeps only intervals at least the task's duration. Slots stay
  maximal: where inside a slot a task lands is the placement step's
  decision. Empty generation (no slot fits) is a fact reported as
  `NO_AVAILABLE_SLOT` downstream, not an error. Reuses
  planned_capacity's interval primitives (same package). 17 tests.
  EPIC-007 started.
- TASK-058 — Hard constraint filtering (2026-09-15): the scheduling
  hierarchy's first layer (docs/05) —
  `domain/constraint_filter.py` with
  `filter_slots_by_constraints`: each candidate slot has every
  constraint's blocked intervals subtracted (merged first, so
  overlapping constraints count once), and the surviving pieces are
  kept only when still at least the task's duration. Subtractive and
  absolute ("Hard constraints are never violated", docs/13);
  half-open boundaries allowed; weekly blocks honor their timezone
  anchor. Semantics mirror `analyze_time_environment`'s treatment of
  constraints (blocks remove availability). A task losing its last
  slot surfaces as `HARD_CONSTRAINT` (docs/06) upstream; here the
  fact is simply a shorter list. 13 tests.
- TASK-059 — Capacity filtering (2026-09-15): the capacity layer of
  the hierarchy (docs/05) — `domain/capacity_filter.py` with
  `filter_slots_by_capacity`, two capacity facts narrowing the
  candidates. The budget gate: a task consumes its duration from the
  goal's pool share (`CapacityPool.allocation_for`); a budget that
  cannot hold the duration empties the list — the `NO_CAPACITY`
  fact (docs/06), the slot-level face of the feasibility rule (a
  feasible plan can still run out of pool share mid-execution when
  other goals consumed theirs). The period window: usable capacity
  is analyzed over a period, so slots are clipped to it (half-open)
  and only in-period pieces ≥ duration survive — time outside the
  period is backed by no analysis. A budget that fits keeps every
  in-period candidate: which one hosts the task is the placement
  step's decision. 12 tests.
- TASK-060 — Dependency filtering (2026-09-15): the dependency layer
  of the hierarchy (docs/05) — `domain/dependency_filter.py` with
  `filter_slots_by_dependencies`: finish-to-start as slot
  arithmetic. Given the finish times of already-placed tasks, a
  slot's usable part begins no earlier than the last direct
  prerequisite's finish — slots are clipped, not destroyed. Only
  direct prerequisites gate: a transitive prerequisite's constraint
  is embodied in its dependent's own placement, so chaining through
  the graph would double-count (documented decision). A prerequisite
  with no finish time is unplaced — the task is
  `DEPENDENCY_BLOCKED` (docs/06) and the result is empty; an
  unplaced prerequisite is a fact to resolve upstream, never
  quietly routed around. 13 tests.
- TASK-061 — Deadline handling (2026-09-16): the deadline layer of
  the hierarchy (docs/05) — `domain/deadline_filter.py` with
  `filter_slots_by_deadline`: a task carrying a deadline must *finish*
  by it. The rule as slot arithmetic: a slot's usable part ends no
  later than the deadline — slots are clipped, not destroyed — and a
  remainder shorter than the task's duration is dropped. Half-open
  semantics: finishing exactly at the deadline is on time. A task
  without a deadline has no deadline layer to apply; its candidates
  pass through untouched. When every candidate falls to the clip the
  task is the `DEADLINE_CONFLICT` failure reason (docs/06) — the fact
  surfaces upstream, the filter simply returns an empty list. The
  final subtractive layer before preference ranking: the hierarchy is
  hard constraints → commitments → dependencies → deadline, and what
  survives is what preferences get to rank. 11 tests.
- TASK-062 — Preference scoring (2026-09-16): the soft layer of the
  hierarchy (docs/05) — `domain/preference_scoring.py` with
  `score_slot` and `rank_slots_by_preferences`. Everything before
  this point was subtractive; preferences never remove anything — a
  slot with a terrible score is still schedulable, merely ranked
  last. Scoring is deterministic and combines the three things a
  Preference carries (TASK-043): each preference contributes its
  weight scaled by the fraction of the slot inside its window
  (positive for PREFER, negative for AVOID), and the slot's score is
  the sum — an AVOID at weight 5 exactly cancels a PREFER at weight 5
  over the same time. Ranking is a stable sort by descending score:
  equal scores keep input order, so chronological generation order
  remains the tie-breaker, and with no preferences every slot scores
  0 — the layer abstains, it never reorders by default. 19 tests.
- TASK-063 — Task splitting (2026-09-16): the placement fallback —
  `domain/task_splitting.py` with `split_task_across_slots` and the
  frozen `SlotAllocation` (slot, start, end). When no single
  surviving slot holds the task's full estimated duration, the work
  flows greedily through the slots in the order given (the
  preference layer ranks them best-first, TASK-062): the best slot
  hosts as much as it can at the planning granularity, the remainder
  flows onward — each slot at most one part, packed from its start,
  parts summing exactly to the duration. The planning granularity is
  the quantum (docs/05: 15 minutes for the MVP): every part is a
  whole multiple of it, and a duration that is not itself a multiple
  is an error — the estimate was made off-granularity and that fact
  should surface, not be silently re-rounded. Insufficient total
  capacity returns empty — the `NO_AVAILABLE_SLOT` fact (docs/06),
  surfaced upstream, never routed around. 16 tests.
- TASK-064 — Schedule persistence (2026-09-16): the placement record —
  `domain/schedule.py` with the frozen `Schedule` (schedule_id,
  task_id, half-open [start, end), created_at), `create_schedule`,
  and `place_task`, plus the `ScheduleRepository` port in
  `domain/repositories.py` (save / get / list_for_task, earliest
  start first). "Schedule: placement of task in time" (docs/02);
  "Task 1:N Schedules" (docs/03) — a split task occupies several
  intervals, so `place_task` turns the TASK-063 slot allocations into
  one Schedule per part. `create_schedule` enforces the task's
  deadline on the persisted placement (finishing exactly at it is on
  time — the same half-open semantics the deadline layer filters by),
  so a stored Schedule can never encode a deadline violation; one
  task's placements must not overlap each other (back-to-back is
  fine). Schedule is distinct from both the Calendar Event it may be
  materialized as and from Execution, and replacing placements never
  rewrites the Plan ("Schedule and Replanning are distinct",
  docs/03). 19 tests.
- TASK-065 — Conflict resolution (2026-09-16): the deterministic half
  of docs/06's principle — "Conflict should first be resolved
  through rescheduling; escalate to replanning only when Plan-level
  feasibility is affected" — `domain/conflict_resolution.py` with the
  frozen `Displacement` (schedule + the exact blocked interval) and
  `ConflictResolution` (action + surviving slots). Who yields follows
  the docs/05 hierarchy: `displace_for_commitments` — an existing
  commitment always displaces a placement (commitments are facts,
  placements are plans); `displace_between_placements` — between two
  placements the later-starting one yields (ties by later end, then
  later id), and a task's own placements overlapping is an invariant
  violation, an error, never quietly "resolved". What happens next:
  `resolve_displacement` — non-empty surviving candidates mean the
  conflict resolves through rescheduling (the slots are where the
  task re-places); empty means no placement exists anywhere, Plan-
  level feasibility is affected, and the action escalates to
  replanning. 19 tests.
- TASK-066 — Rescheduling (2026-09-16): level 1 of the adaptation
  ladder (docs/08) — "Reschedule — move time only" —
  `domain/rescheduling.py` with `reschedule_task` and the frozen
  `RescheduleResult` (removed / kept / placed: delete by id, leave,
  save). The displaced placements (TASK-065) are withdrawn and the
  same work re-places into fresh slot allocations, while the
  untouched placements stay exactly where they are — the minimum-
  change principle (docs/08) made structural: only displaced time
  moves. Invariants: the re-placed workload equals the withdrawn
  workload to the tick (a change in amount is a re-estimation and
  belongs to replanning); new placements respect the task's deadline
  (via place_task, whose ScheduleError propagates — inner-error
  precedent) and overlap neither one another nor the kept placements
  (one task, one place at a time); all new placements share the
  reschedule instant as created_at. The Plan, tasks, and workload
  are untouched — "Schedule and Replanning are distinct" (docs/03).
  16 tests, including the conflict-to-reschedule end-to-end path.
- TASK-067 — Rolling horizon (2026-09-16): the operational window
  and what it exacts — `domain/rolling_horizon.py` with `Horizon`
  (half-open [start, end), `contains`), `operational_horizon`
  (default two weeks, docs/06; each call re-derives the window from
  the current instant — that re-derivation is the rolling), and
  `split_tasks_by_horizon` → `HorizonSplit` (exact /
  approximate, input order preserved). Classification: a task is
  *due* when its deadline falls no later than the horizon's end
  (overdue counts as due); a milestone is *near* when its target
  date does, and a task serving a near milestone's outcome is
  *anchored* into the exact zone (long-term milestones keep
  approximate allocation); due and anchored tasks pull their
  transitive prerequisites in with them — an exact task is
  unplaceable while its prerequisites are unplaced (docs/05 puts
  dependencies above deadline). Everything else stays approximate
  until the window rolls over it. 20 tests.
- TASK-068 — Scheduler integration (2026-09-16, EPIC-007 complete):
  the epic-closing composition — `domain/scheduler.py` with
  `schedule_tasks` → `SchedulingResult` (placements + failures in
  dependency order, remaining budget; `placed_task_ids`,
  `failure_reasons`). Per task, in topological order: generate
  candidates → subtract constraints → capacity gate → dependency
  clip → deadline clip → preference ranking → split → place, with
  each placement's finish gating its dependents and consuming from
  the budget the next task sees. Composition decision (documented):
  the subtractive layers receive the granularity as their minimum
  piece — the splitter's quantum — not the task's full duration;
  a layer handed the full duration would keep only whole-task-sized
  pieces and starve the splitter (a 10-hour task against 8-hour
  days would find nothing instead of flowing 8 + 2 across two
  days), while the budget gate stays on the full duration (a
  placement consumes its whole estimate from the pool). Failures
  surface with the docs/06 reason of the layer that caused them
  (`FailureReason`: NO_CAPACITY, NO_AVAILABLE_SLOT, HARD_CONSTRAINT,
  DEPENDENCY_BLOCKED, DEADLINE_CONFLICT, plus UNESTIMATED_TASK from
  plan validation) and propagate down the dependency chain as
  DEPENDENCY_BLOCKED without retry loops. EPIC-007 complete;
  EPIC-008 started. 21 tests.
- TASK-069 — Execution model (2026-09-16): the Actual of docs/07's
  "Planned ≠ Actual ≠ Progress" triad — `domain/execution.py` with
  the frozen `Execution` (execution_id, task_id, half-open
  [start, end), created_at, `.duration`), `create_execution`,
  `executions_for_task`, and `actual_duration` (the Actual
  counterpart of `estimate_workload`; empty sum zero). "Execution:
  what actually happened" (docs/02); "Task 1:N Executions"
  (docs/03) — one record per sitting. The mirror image of Schedule
  with the opposite epistemology: no deadline enforcement (a missed
  deadline is exactly the variance signal, refusing to record it
  would erase the deviation), no granularity rounding (work took
  what it took; the 15-minute quantum is a planning concern), no
  consistency demand against placements (executing outside the
  placed time is a schedule variance, recorded by both records
  simply existing). 15 tests.
- TASK-070 — Measurement model (2026-09-16): the observation half of
  docs/02's "Measurement: observed data" — `domain/measurement.py`
  with the frozen `Measurement` (measurement_id, metric held by
  value, value, measured_at, optional subject_id),
  `record_measurement`, `measurements_for_subject`, and
  `latest_measurement` (ties to the last in input order; empty is
  None). The Metric (TASK-015) is the definition; a Measurement is
  one observed value of it, taken at one moment about one subject —
  "intermediate measurable checkpoint" (docs/02) means a milestone
  becomes measurable by being observed. Invariants: the value is
  validated against the metric's kind and score scale (out-of-type
  is a recording error, not a deviation to interpret); the
  measurement is an immutable fact of history like ObservedCapacity
  — no updated_at, corrections arrive as new records. Association
  decision: docs/03 fixes Milestone/Outcome without a metric link,
  so the optional subject_id (milestone or outcome UUID) lives on
  the measurement side; a subjectless measurement is a free-standing
  observation of the metric itself. `MeasurementRepository` port
  added (save / get / list_for_subject, earliest measured_at first).
  24 tests.
- TASK-071 — Progress snapshots (2026-09-16): the third term of
  docs/07's triad — `domain/progress.py` with the frozen
  `ProgressSnapshot` (snapshot_id, plan_id, taken_at, task_count,
  completed_task_count, planned, actual, remaining, progress,
  completion_rate) and `take_progress_snapshot(plan, tasks,
  executions, *, at)`. Derivation, all mechanical: planned =
  `estimate_workload` (unestimated tasks propagate the estimation
  error — unknown workload, no derivable progress); actual sums only
  the sittings for these tasks that ended at or before the snapshot
  moment (a sitting in progress has not actually happened yet);
  progress and completion_rate are capped at 1.0 — a plan cannot be
  more than done, overruns are the variance layer's material
  (docs/07), the same separation that keeps Execution free of
  judgment; remaining floors at zero; completion is per task (own
  actual ≥ own duration), so overwork on one task does not complete
  its sibling; an empty task list reports zero everywhere.
  `ProgressSnapshotRepository` port added (save / get /
  list_for_plan, earliest taken_at first) — an append-only history,
  the progress counterpart of CurrentState snapshots. 18 tests.
- TASK-072 — Velocity (2026-09-16): the base rate beneath the
  docs/07 signals — `domain/velocity.py` with the frozen `Velocity`
  (window_start, window_end, worked, rate) and
  `compute_velocity(executions, *, at, window)`. Semantics: the
  window is calendar time, not workable time — velocity says how
  much work materialized per calendar day at the observed pace, and
  comparing that against capacity is the sustainability layer's
  judgment; a sitting contributes only the part inside the window,
  clipped at both edges (a straddler's pre-window tail and
  post-`at` overhang do not count); `rate` is the dimensionless
  window fraction, `per_day` restates it as a timedelta of work per
  calendar day — the form projections consume (remaining ÷ per_day
  = time to finish, demonstrated in wiring with a progress
  snapshot). The empty window reads zero: no work recorded is
  itself the observation. Computed, not stored — like Variance, no
  repository. 13 tests.
- TASK-073 — Variance signals (2026-09-16): the four
  time-denominated instances of docs/02's "Variance: planned vs
  actual difference" — `domain/variance.py` with `VarianceKind`
  (PROGRESS/TIME/CAPACITY/SCHEDULE), the frozen `Variance` (kind,
  planned, actual, delta, favorable; delta must equal
  actual − planned — one sign convention for all four), and four
  constructors. `progress_variance(snapshot)`: workload done vs
  planned, more is favorable. `time_variance(task, executions)`:
  actual duration vs estimate, less is favorable; unestimated task
  errors (no planned side). `capacity_variance(windows, events,
  observed)`: the planned side is recomputed with workable_time over
  the observed record's own period, so both sides always describe
  the same range; more observed capacity is favorable.
  `schedule_variance(schedules, executions)`: placed time vs the
  part actually worked inside the placements (per matching task,
  clipped at the edges); work outside placements is a timing fact
  the other signals carry — this one measures adherence. The
  timedelta sibling of metric.interpret_variance (TASK-015), whose
  direction-aware reading covers metric-typed values; here the
  direction is inherent in the signal. What to *do* about a
  variance is docs/08's ladder, upstream. 27 tests.
- TASK-074 — Trend analysis (2026-09-16): the docs/07 "trend"
  signal on top of velocity — `domain/trend.py` with
  `TrendDirection` (ACCELERATING/STEADY/DECELERATING), the frozen
  `Trend` (direction, recent, previous; post-init enforces
  consecutive equal-length windows and that the direction matches
  the rates), `analyze_trend(velocities)` (the last two windows
  decide; fewer than two cannot show a direction), and
  `project_completion(snapshot, velocity)` — remaining workload
  scaled by the window's work-to-span ratio, added to the snapshot's
  moment; None when already complete or at zero pace (observations,
  not errors). Composition decisions: the direction is a strict
  rate comparison — no smoothing or tolerance band, a trend
  statement is only as good as its windows are honest; the
  projection scales by remaining/worked × span rather than dividing
  by the derived per-day rate (algebraically identical, but the
  single division avoids compounding float error into the ETA).
  17 tests.
- TASK-075 — Goal health (2026-09-16): the roll-up where docs/07's
  signals meet — `domain/goal_health.py` with
  `on_time_rate(tasks, executions, *, at)` (the last signal on the
  list: of finished deadline-bearing tasks, the fraction finished
  by deadline; the completion moment is when cumulative actual
  first reaches the estimate, so overwork sittings after an
  on-time finish are not lateness; deadlineless tasks are not
  counted; unestimated deadline tasks make the rate unknown, the
  estimate_workload stance; None when nothing finished — no
  evidence either way), `GoalHealthStatus`
  (ON_TRACK/AT_RISK/OFF_TRACK), the frozen `GoalHealth` (status,
  reasons; a non-on-track reading must carry reasons), and
  `assess_goal_health(snapshot, *, variances, trend, deadline,
  projected_completion, on_time)`. Every rule explicit with a
  machine-readable reason slug: complete plan → ON_TRACK
  ("plan-complete", outranking everything — nothing left to
  project); projected completion past the deadline → OFF_TRACK
  ("projected-deadline-miss"); any unfavorable variance
  ("unfavorable-<kind>-variance"), decelerating trend
  ("decelerating-trend"), or late completions
  ("late-completions") → AT_RISK; nothing triggered → ON_TRACK
  with no reasons. Ordering off-track > at-risk > on-track is
  fixed; what to do about a poor reading is docs/08's ladder,
  upstream. 27 tests.
- TASK-076 — Sustainability (2026-09-16): the judgment velocity
  declined to make — `domain/sustainability.py` with
  `SustainabilityStatus` (SUSTAINABLE/UNSUSTAINABLE), the frozen
  `Sustainability` (status, worked, workable, utilization,
  max_utilization; post-init enforces utilization = worked/workable
  and status consistency), and `assess_sustainability(velocity,
  windows, events, *, max_utilization=1.0)` — the workable side
  recomputed with workable_time over the velocity's own window
  (same-period guarantee as capacity variance). Rules: working
  beyond the workable time is unsustainable whatever the ceiling —
  those hours come from time the user did not declare workable
  (evenings, weekends, protected time), the burnout signal; the
  default ceiling 1.0 is the availability declaration's own
  semantics (docs/05 — the user said this time is workable); a
  lower ceiling (e.g. 0.8) encodes leave-headroom policy without
  touching the declaration; no workable time → utilization None,
  and any work over zero workable time is still beyond capacity.
  13 tests, including the wiring where a plan completes on time
  via an evening sprint: progress ON_TRACK and pace UNSUSTAINABLE —
  both readings stand.
- TASK-077 — Explicit feedback (2026-09-16): "explicit user
  statements" (docs/07) — `domain/feedback.py` with `FeedbackKind`
  (EXPLICIT/IMPLICIT, docs/02's split; implicit arrives in
  TASK-078), the frozen `Feedback` (feedback_id, kind, statement,
  created_at, optional subject_id; statement stripped and bounded
  at 5000 chars), `record_feedback` (default kind EXPLICIT), and
  `feedback_for_subject`. The statement is kept verbatim and
  deliberately unclassified — no sentiment, no category, no parsed
  intent: a statement the domain has pre-classified is one the
  reasoning layer can no longer see honestly (ADR-002 — the LLM
  proposes and reasons, the Domain validates and enforces);
  interpretation happens upstream of replanning (docs/08), where
  the statement and the signals meet. Immutable like every
  observation (measurement precedent): no updated_at, corrections
  are new statements. `FeedbackRepository` port added (save / get /
  list_for_subject / list_all, earliest created_at first).
  18 tests.

- TASK-078 — Implicit feedback (2026-09-16): docs/02's other half,
  "implicit behavioral signals" (docs/07) — derived mechanically from
  the behavior records, stated as factual sentences, returned only
  when the behavior is present (absence is not a signal).
  `detect_work_outside_availability(executions, windows, events=(),
  *, at)` — per sitting, workable time over the sitting's own
  interval (the shared capacity semantics: availability minus
  commitments); the rest is behavior contradicting the declaration.
  `detect_work_outside_placements(executions, schedules, *, at)` —
  only sittings of tasks carrying at least one placement count (no
  placement is a planning concern, not a behavioral one); inside is
  the overlap with that task's placements. Both return `Feedback`
  with kind IMPLICIT via `record_feedback` — derived signals share
  the record, so they store, filter, and travel like explicit
  statements. 15 tests. EPIC-008 complete.
- TASK-079 — Trigger model (2026-09-16): the record the replanning
  layer's judgement is made about (docs/08). `domain/trigger.py`
  with `TriggerKind` — the ten trigger sources verbatim (progress,
  capacity, time, calendar, constraint, resource, dependency,
  behavior, goal, system) — the frozen `Trigger` (trigger_id, kind,
  detail, observed_at; detail stripped and bounded at 2000 chars,
  observed_at UTC), `raise_trigger`, and `triggers_of_kind` (input
  order). A trigger states what was seen and when; it decides
  nothing — persistence thresholds (TASK-080/081), cooldown
  (TASK-082), and the reschedule/replan/goal-revision ladder are
  upstream, and detection (which signal raises which trigger) stays
  with the signals modules per ADR-002. Immutable like every
  observation. `TriggerRepository` port added (save / get /
  list_all, earliest observed_at first) — the stability controls
  read trigger history. 19 tests, including the wiring where a
  behavioral signal becomes a BEHAVIOR trigger.

- TASK-080 — Thresholds (2026-09-16): the magnitude bounds of
  docs/08's stability controls — how far a reading must slip before
  it is trigger-worthy at all. `domain/threshold.py` with `Measure`
  (SHORTFALL — a duration; UTILIZATION and COMPLETION — rates), the
  frozen `Threshold` (measure, enter_bound, exit_bound defaulting to
  enter_bound): bounds are type-checked per measure family,
  non-negative, and exit must not exceed enter. Setting the bounds
  apart is hysteresis — 4h-behind enters, 2h-recovered clears, and
  the gap between does not flap; evaluation is enter-wins at the
  boundary (`is_exceeded` at >=, `has_cleared` at <=). The
  adapters reduce records to the slip a threshold weighs:
  `variance_shortfall` (the unfavorable side of any Variance — a
  favorable variance contributes zero, whatever its size),
  `utilization` (None, no declared workable time, reads as 0 — the
  beyond-capacity judgement lives in the reading's own status), and
  `completion_shortfall` (1 - completion_rate). Persistence
  detection (TASK-081) counts consecutive crossings of these;
  cooldown (TASK-082) times them. 30 tests, including the recovery
  wiring where week two's work falls through the exit bound.

- TASK-081 — Persistence detection (2026-09-16): the same
  condition, observed repeatedly. `domain/persistence.py` with
  `Persistence(required)` — the count of consecutive observations
  that confirms a condition (int, at least 1) — the frozen
  `PersistenceReading(active, consecutive)` with `confirms()`
  (an inactive reading never confirms; an inactive condition cannot
  claim a run), and `assess_persistence(threshold, magnitudes)`:
  TASK-080's hysteresis state machine run over a chronological
  series of observed magnitudes. Semantics: entering wins (an
  observation at the enter bound enters or re-enters, even on equal
  bounds); an observation at or below the exit bound clears and
  resets; an observation in the hysteresis gap holds — the run
  counts on, which is the point: a condition that dipped without
  recovering has not stopped being a state of the world. Bad
  magnitudes restate ThresholdError as PersistenceError. 21 tests,
  including the wiring where one hour a week on an 8h task (slips
  7h/6h/5h, cumulative snapshots) confirms at three weeks, and a
  single bad week between clear ones never does.

- TASK-082 — Cooldown (2026-09-16): the timed half of docs/08's
  stability controls — persistence asks "has this held?", cooldown
  asks "did we just act on it?". `domain/cooldown.py` with
  `Cooldown(period)` (non-negative timedelta; zero is no cooldown at
  all), `in_cooldown(cooldown, last_action_at, *, at)` — suppressed
  strictly within the period, free at the moment it ends — and
  `cooldown_remaining` (the suppressed time left, zero when free).
  The clock is deliberately just a clock: which actions start which
  clocks (per trigger kind, per plan, per run) is bookkeeping for
  the replanning policy (TASK-083) and the decision engine
  (TASK-084). `at` must not precede the action it asks about.
  15 tests, including the wiring where a re-confirmed condition
  waits out its week before the system may act again.

- TASK-083 — Replanning policy (2026-09-16): docs/08's vocabulary
  assembled into one stance. `domain/replanning_policy.py` with
  `ReplanningLevel` (RESCHEDULE / REPLAN / GOAL_REVISION, the
  adaptation ladder) and `ReplanningMode` (MANUAL / SUGGEST /
  AUTOMATIC); the frozen `ReplanningPolicy(mode, cooldown,
  persistence)` — one plan's assembled stability controls plus its
  mode. The policy gates, it does not choose (which level a
  condition warrants is TASK-084's decision engine): `permits()`
  (only AUTOMATIC acts, only on the lower levels, only outside
  cooldown — a goal revision is never automatic, docs/08's
  "explicitly change the destination": the destination is the
  user's) and `suggests()` (only SUGGEST proposes; suggestions are
  cooled down like actions — a suggestion just declined is not
  repeated hourly; MANUAL neither acts nor proposes; AUTOMATIC has
  no need to suggest what it may do). `minimal_level` is the
  minimum-change principle, docs/08's fourth stability control: the
  lowest level that addresses the condition wins — the same ladder
  docs/06 fixes for conflicts. Levels are distinct from
  conflict_resolution's ResolutionAction (per-displacement outcome)
  and trace through plan_version. 24 tests.

- TASK-084 — Replanning decision engine (2026-09-16): the last
  joint of docs/08's adaptation machinery — proposal in, decision
  out. `domain/decision_engine.py` with `DecisionAction`
  (ACT/SUGGEST/HOLD), the frozen `ReplanningDecision(action,
  level, reason)` — acting and suggesting require a level; reason
  is a machine-readable slug naming the control that decided — and
  `decide_response(policy, reading, levels, *, last_offered_at,
  at)`. Per ADR-002, the reasoning layer proposes the candidate
  levels; the engine enforces: the reading must confirm against
  the policy's own persistence ("not-persistent"), the
  minimum-change principle picks among the candidates
  ("no-candidate" when empty), and the policy gates say act /
  suggest / hold ("manual-mode", "cooldown",
  "goal-revision-requires-user"). The engine never invents a
  level; executing it is downstream (rescheduling for level 1,
  TASK-085 through TASK-087 for level 2, the user for level 3),
  with the trace in a plan version. 18 tests, including the full
  wiring from sittings to decision and the same condition waiting
  out its cooldown.

- TASK-085 — Local replan (2026-09-16): level 2 at its narrowest
  scope — one task revised in place, the Goal/Future untouched.
  `domain/local_replan.py` with the frozen `LocalReplan(scope,
  plan, task, version)` (scope pinned LOCAL; task and version must
  belong to the plan) and `replan_task_locally(plan, history,
  task, *, reason, ...)`: the revision flows through `revise_task`
  (title/description/duration/deadline; None keeps), the plan's
  workload moves by the estimate's delta — the plan keeps whatever
  basis its workload was declared on; a local replan shifts it, it
  does not recompute it, and an estimate landing on an unestimated
  task grows the workload by its full amount — and the trace is a
  PlanVersion whose change set names the revised task. To support
  that, `PlanChangeSet` gained `revised_task_id` (backward
  compatible, None-keeps) and `apply_plan_version`'s
  meaningfulness check now accepts a task revision without a
  workload move (a re-committed deadline is a meaningful replan
  that changes no sizes). A revision that changes nothing is
  rejected; negative resulting workloads surface the plan-version
  invariant. `ReplanScope` (LOCAL/REGIONAL/GLOBAL) added to
  replanning_policy as the shared scope ladder for TASK-086/087.
  17 tests, including the arc from trigger to decision to the
  re-estimate.

- TASK-086 — Regional replan (2026-09-16): level 2 at middle
  scope — a dependency-connected group of tasks revised as one
  decision, one reason, one plan version (revising the region
  task-by-task would tell one decision in several versions).
  `domain/regional_replan.py` with `TaskRevision(before, after)`
  (identity kept; a revision that changes nothing is rejected),
  `dependency_region(seed, tasks, dependencies)` — the seed plus
  every task connected through the dependency graph, both
  directions (a re-estimate moves work for prerequisites and
  dependents alike), topologically ordered; unlinked tasks stay
  out — the region is the ripple, not the plan. The boundary is
  mechanical; whether the proposed revisions cover it is the
  reasoning layer's judgement (ADR-002).
  `replan_tasks_regionally(plan, history, revisions, *, reason)` —
  distinct tasks of the plan only, workload moves by the summed
  estimate deltas (shift-not-recompute, same rule as TASK-085;
  opposite-direction deltas net out; an estimate landing counts in
  full), one version naming every revised task. To carry several
  tasks, `PlanChangeSet.revised_task_id` generalized to
  `revised_task_ids: tuple` (local replan updated mechanically;
  its 17 tests and plan_version's 25 still green). 23 tests,
  including the region moving as one decision while an unlinked
  task stays untouched.

- TASK-087 — Global replan (2026-09-16): level 2 at its widest
  scope — the whole plan re-derived, the Goal/Future untouched.
  `domain/global_replan.py` with the frozen `GlobalReplan(scope,
  plan, version)` (scope pinned GLOBAL) and
  `replan_plan_globally(plan, history, tasks, *, reason,
  title=None, source_run_id=None, at=None)`. The scope distinction
  that defines it: local and regional *shift* the plan's workload
  by their estimate deltas (the rest of the declaration still
  stands); a global replan changes everything, so there is nothing
  left to preserve — the workload is recomputed from the task set
  via `estimate_workload`, whose refusal to sum over unestimated
  tasks surfaces here too (a global replan that cannot face its own
  task set's estimates cannot re-derive the plan). A re-derivation
  landing on the same workload and title changes nothing and is
  rejected. 15 tests, including the arc from trigger to decision
  to re-derivation, and the three scopes sharing one version trail
  (local v1, regional v2, global v3 — 20h declared, 11h
  recomputed).

- TASK-113 — Calendar UI (2026-09-16): the user-scoped calendar
  joins the top level. New read path `GET /users/{user_id}/calendar`
  (the browser holds the user id — the MVP's scoping convention —
  so the lookup is by user, not by a calendar id the client would
  have to remember); contract regenerated. On the web: the
  `/calendar` route with `CalendarBoard` (client, like the goal
  board) — create the one-per-user calendar with an optional IANA
  home zone, list events earliest first, place events with aware
  datetime inputs, and surface the domain's conflict detection as
  an alert list when events overlap. The site header became a
  client component to mark the current entry from the pathname
  (two top-level areas now). 5 new backend tests (suite: 2342);
  smoke-tested live through the Next proxy (404 → create → 200,
  one-per-user 409, ordered events, the overlap detected and named,
  backwards event 422).

- TASK-112 — Task UI (2026-09-16): assembly-time task revision. A
  task on a DRAFT plan is editable — fix a title, land a missing
  estimate, set or move a deadline — closing the gap TASK-111 left
  open: tasks could be added without an estimate, but publishing
  refuses unestimated ones, so such a plan could never publish.
  Revision rides the domain's `revise_task` (omitted fields keep
  their value; the plan's workload stays untouched until publish
  recomputes it); revising a published plan's task is the
  replanning ladder's LOCAL scope (docs/08) and is rejected here
  (409 `PlanNotDraftError`), as is a task that is not on the goal's
  plan (404 `NoTaskError`). New endpoint: `PATCH
  /goals/{goal_id}/plan/tasks/{task_id}` (contract regenerated).
  On the web, `TaskEditForm` (client, collapsed behind "Edit task"
  on each draft task row) and a deadline field on task creation;
  `PlanView` gained a per-task edit slot and shows deadlines. 23
  tests; smoke-tested live through the Next proxy (revise → publish
  sums the revised estimates; late revision 409; unknown task 404).

- TASK-111 — Plan UI (2026-09-16): plan assembly and publishing.
  Beginning a plan finishes the goal's run and opens a DRAFT with
  run provenance; outcomes (optionally bound to a milestone of the
  goal) and tasks (with hour estimates, optionally serving
  outcomes) assemble on the draft; publishing computes the workload
  as the sum of task estimates and freezes the plan as CANDIDATE —
  one plan per goal, enforced at the service and HTTP layers (409).
  New ports: `PlanRepository`, `OutcomeRepository`, `TaskRepository`
  with in-memory implementations; `PlanService`; and five endpoints
  (`POST/GET /goals/{goal_id}/plan`, `.../plan/outcomes`,
  `.../plan/tasks`, `.../plan/publish`) with the full status
  mapping (unestimated tasks at publish surface as 422 via
  `TaskEstimationError`, frozen plans as 409). The goal detail page
  grows the plan section: `BeginPlanForm` before a plan exists,
  `PlanView` with assembly forms while DRAFT (publish disabled
  until a task carries an estimate), and the status plus computed
  workload once published. 28 tests; the contract is regenerated
  and the flow was smoke-tested live through the Next proxy (begin
  → outcome/task → publish → candidate with 3h workload, late
  assembly 409, unestimated hints).

- TASK-110 — Milestone UI (2026-09-16): checkpoints on the
  backcasting run. The domain already required milestones to be
  defined during a RUNNING run, so `define_backcast` now starts the
  run over its context (`start_run` validates the gap belongs to
  exactly that current/future pair) and the run ships in the
  backcast bundle and API response. New ports:
  `BackcastingRunRepository` (list/latest per goal) and
  `MilestoneRepository` (list per run, earliest target first) with
  in-memory implementations; `MilestoneService` pins checkpoints on
  the goal's current run — 404 for an unknown goal or a goal with
  no run yet, 422 for the domain's refusals (blank title, target at
  or before now, a finished run). HTTP: POST/GET
  `/goals/{goal_id}/milestones`. Frontend: below the backcast chain,
  a server-rendered ordered `MilestoneList` (the path walked in
  order) plus the client-side `MilestoneForm` with
  `router.refresh()`. 20 new tests (backcast run assertions
  extended); backend 2286 green; contract regenerated; `npm run
  verify` and `next build` green; verified live end to end
  (backcast → two milestones ordered on the page → 422 past target
  → 404 without backcast).

- TASK-109 — Backcasting visualization (2026-09-16): pipeline
  steps 1–4 of docs/04 surfaced as one capability. Backend: a
  `GapRepository` port (a gap is a recorded calculation, not just a
  derived value — one per goal in the MVP), in-memory
  implementations for current/future/gap with the one-per-goal
  invariants enforced at the port, `BackcastService.define_backcast`
  composing capture_current_state → define_future_state →
  calculate_gap with the context validation the domain requires,
  and `get_backcast` reassembling the bundle from the latest
  snapshot. HTTP: POST/GET `/goals/{goal_id}/backcast` — 404
  (unknown goal or nothing defined), 409 (one per goal; redefining
  arrives with replanning), 422 (blank narratives, past or naive
  target date). Frontend: the goal detail page renders the chain —
  Now → The gap → Destination cards — server-side, or the
  definition form (client component, `router.refresh()` after
  submit) when no backcast exists. Fixed a real bug the new
  service exposed: `create_app` was materializing the default
  goal repository twice, so goal-service writes were invisible to
  the backcast service. 20 new tests; backend 2266 green;
  contract regenerated; `npm run verify` and `next build` green;
  verified live end to end (form → 201 → chain renders → second
  definition 409).

- TASK-108 — Goal detail (2026-09-16): the read-only goal view.
  The backend already served GET /goals/{goal_id} (TASK-107), so
  this is a web task: the dynamic route
  `src/app/goals/[goalId]/page.tsx` renders server-side from the
  backend via `src/lib/server-api.ts` — the same `API_ORIGIN` knob
  the rewrites use, because Next rewrites apply only to incoming
  browser requests, not to a server component's own fetch. Unknown
  goals map to Next's not-found boundary; an unreachable backend
  renders the error state rather than crashing the render. The
  board's list entries now link to each goal's detail page
  (`next/link`). Structural assertions in `verify-shell.mjs`
  (route exists, notFound wiring, force-dynamic, board links,
  server-api uses API_ORIGIN); `npm run verify`, `next build`
  (route `ƒ /goals/[goalId]`), and the full 2246-test backend
  chain green. Verified live end to end: create via the /api
  proxy, server-rendered detail page, 404 for unknown ids.

- TASK-107 — Goal creation (2026-09-16): the first product
  capability end to end. Backend: `InMemoryGoalRepository`
  (insert-or-replace, `(created_at, goal_id)` ordering),
  `GoalService` (create/get/list with `GoalNotFoundError` as the
  presentation-layer's 404 signal), and the `/goals` HTTP surface
  — POST 201, GET by id (404 unknown), GET list scoped to the
  client-supplied `user_id` (no auth in the MVP, the calendars
  convention); domain violations map to 422. The OpenAPI contract
  regenerates with the three goal operations (ADR-008). Frontend:
  the goals home becomes interactive — a client-side `GoalBoard`
  composing the TASK-105/106 primitives (TextField, Button, Card),
  mirroring the domain's title rule client-side with the server's
  message shown for anything past it; `next.config.ts` rewrites
  `/api/*` to the backend (`API_ORIGIN`, default localhost:8000)
  so the browser talks to one origin; and the browser-identity
  convention (`src/lib/user.ts`) holds a localStorage UUID — a
  scoping convention, not a security boundary, replaced when
  EPIC-012 brings auth. 25 new tests (repo/service/HTTP/contract),
  structural assertions in `verify-shell.mjs`; backend 2246 green,
  `npm run verify` and `next build` green.

- TASK-106 — Tailwind setup (2026-09-16): the Tailwind CSS
  pipeline over the TASK-105 tokens, per ADR-005's
  "token-driven component system". `tailwindcss` and
  `@tailwindcss/postcss` pinned exactly at 4.3.3 (ADR-007
  baseline), wired through `postcss.config.mjs`; `globals.css`
  imports `tailwindcss` and aliases the runtime tokens into the
  theme namespaces with `@theme inline` — colors
  (`--color-surface: var(--surface)` …), spacing, and radii. The
  runtime tokens were renamed unprefixed (`--surface`, `--text`,
  `--radius-medium`, …) because a theme entry must never reference
  itself; the hand-written component classes follow the same
  runtime variables. `@theme inline` is the load-bearing choice:
  the emitted utilities are `bg-surface-muted
  {background-color:var(--surface-muted)}`,
  `p-5 {padding:var(--space-5)}` — runtime variables, not
  build-time-resolved values — so the dark-mode palette swap moves
  utilities and component classes together, with no frozen light
  values (verified by grepping the built CSS). The `/design`
  showcase gained a utilities card exercising the generated
  classes. Verify scripts updated: shell asserts the 4.3.3 pin,
  design asserts the PostCSS wiring and the theme mappings;
  `npm run verify` + `next build` green (4/4 routes).

- TASK-105 — Design system (2026-09-16): the token vocabulary
  and the reusable primitives the feature UIs (TASK-107+) compose
  — AGENTS.md §6's "build reusable primitives before
  feature-specific UI duplication" made concrete.
  `src/styles/tokens.css`: the design tokens as CSS custom
  properties — semantic colors (surface/text/border, primary with
  a hover state, danger, focus), a 4px spacing scale, a type
  scale, radii, and one card shadow — with the palette swapped for
  dark mode via prefers-color-scheme so only values move, never
  names. TASK-106 maps these into Tailwind's @theme (ADR-005's
  "token-driven component system"). Primitives in
  `src/components/ui/`: `Button`/`ButtonLink` (primary/secondary/
  danger variants; defaults to type=button so a stray primitive
  never submits a form), `TextField` (label required by type,
  htmlFor/id wiring, aria-describedby for hint and error,
  aria-invalid, the error a role=alert live region, useId
  fallback), and `Card` (titled surface with an actions slot).
  The shell styles now consume the tokens. `src/app/design/page.tsx`
  is the living style guide rendering every primitive against the
  tokens. Automated checks: `scripts/verify-design.mjs` (chained
  into `npm run verify` — asserts the token vocabulary, the
  accessible wiring of each primitive, and showcase coverage)
  plus `tsc --noEmit` and `next build` (4/4 static routes). No new
  dependencies.

- TASK-104 — App shell (2026-09-16): the EPIC-011 opener — the
  Next.js skeleton the feature UIs land in. `apps/web` scaffolded
  to the ADR-007 baseline (next 16.3.5, react/react-dom 19.3.0,
  typescript 5.9.3, exact pins; @types pinned to what the registry
  serves): root layout with `lang`, a skip link to the main
  landmark, the `SiteHeader` (server component — the shell has no
  client state) with labelled primary navigation (Goals, the MVP's
  single entry point; every other area lives inside a goal's
  detail view), a footer, and the goals home route. Styling is
  deliberately minimal plain CSS: design tokens are TASK-105 and
  the Tailwind pipeline TASK-106, so the shell ships structure
  only (and the verify script asserts tailwindcss is absent from
  package.json until then). Automated checks: `npm run verify`
  (scripts/verify-shell.mjs — landmarks, skip link, nav labels,
  route presence, version pins — plus `tsc --noEmit`) and
  `next build` (3/3 static pages, Next's mandatory tsconfig
  adjustments kept). No JS test runner exists in the baseline and
  none was added silently. `*.tsbuildinfo` ignored.

- TASK-103 — AI fallback (2026-09-16): the EPIC-010 closer — the
  graceful-degradation policy. Every AI operation has a
  deterministic alternative (hand-written proposals through the
  same acceptors), so degradation is a designed path, not an
  apology. `domain/ai_fallback.py`: the frozen `Fallback(reason)`
  record — mandatory, bounded, an immutable fact with the same
  discipline as the verbatim proposal records, so the audit trail
  always says why the AI was bypassed. `application/ai_fallback.py`:
  `FALLS_BACK_ON = (ProviderCallError, ProposalParseError)` —
  vendor faults and never-validating proposals (already retried to
  their limit) degrade; `attempt_strategies/outcomes/tasks` wrap
  the validated-generation use cases, returning the result and no
  fallback on success, or the reason the deterministic path must
  take over. Permission denials and LLMProviderError stay loud —
  silently degrading a misconfiguration replaces a loud bug with a
  quiet wrong behavior. Fallback attempts write no proposal
  record, only their reason. 12 tests
  (`tests/test_ai_fallback.py`), including the policy's exact
  failure set and both manual paths still working after a
  fallback. EPIC-010 is complete: six operation records, the
  provider port with three vendor adapters, context building,
  schema validation with retry limits, tool permissions, the
  evaluation dataset, and fallback.

- TASK-102 — AI evaluation dataset (2026-09-16): a regression net
  for the AI pipeline. `apps/api/evals/ai_operations.json`: six
  golden cases (two per evaluable operation — strategy generation,
  outcome decomposition, task generation; the prose-only operations
  have no deterministic target to evaluate against), each carrying
  the backcast anchors and one golden response.
  `application/evaluation.py`: `load_dataset` (strict — unknown
  operations, duplicate case ids, bad dates/workloads, and missing
  per-operation fields are dataset errors), `run_case`/`run_dataset`
  — each case replays through the full deterministic arc: build the
  records, build the context, feed the golden response through a
  scripted provider, parse under the operation's schema, and pass
  the parsed proposals through the deterministic acceptors
  (accept_proposed_strategies behind calculate_gap + start_run,
  define_outcome, accept_proposed_tasks), reporting one verdict per
  case. Reproducible by construction: ids are UUID v5 of the case
  id and timestamps a fixed epoch, so a case that flips means the
  code changed. 17 tests (`tests/test_ai_evaluation.py`),
  including every-dataset-case-green, coverage of all three
  operations, honest failure detail, and reproducibility.

- TASK-101 — Tool permissions (2026-09-16): docs/09's
  permission-validation and tool-allowlist guardrails. In this
  architecture the LLM has no free-form tools — everything the
  reasoning layer can do is one of the six AI operations, carried
  on every LLMRequest — so the operation name is the tool and the
  allowlist is a set of operation names. `domain/tool_permissions.py`:
  `AI_OPERATIONS` (the six, kept in lockstep with the context
  builder's instruction table by test), the frozen
  `ToolPermissions` allowlist with `permits`/`require`/
  `require_request`, and `grant_operations`/`all_operations`/
  `no_operations` constructors. Construction is strict: unknown
  operation names are configuration errors, not silent no-ops; an
  empty allowlist (a deployment with no AI) is valid. The
  enforcement point is structural: `application/permission_guard.py`'s
  `PermittedProvider` wraps any provider and validates each
  request's operation before the vendor is reached — a denied
  operation raises before any request leaves the process; vendor
  faults propagate untouched. Environment wiring: `Settings`
  gains `ai_operations` parsed from a comma-separated
  `AI_OPERATIONS` env var (unset permits all six, empty denies
  all, unknown names fail fast), with a commented line in
  `.env.example`. 20 tests (`tests/test_tool_permissions.py`),
  including the env → Settings → allowlist → guard arc.

- TASK-100 — AI validation (2026-09-16): docs/09's
  schema-validation guardrail — the layer every AI-operation record
  deferred to. `domain/proposal_parsing.py`: the wire contract is
  JSON, extracted tolerantly (whole text, fenced block, or first
  balanced span — an unbalanced opening is malformed, not missing)
  and then enforced strictly: `parse_strategy_proposals` →
  StrategyProposal tuples, `parse_outcome_titles` → titles,
  `parse_task_proposals` → TaskProposal tuples (duration_hours,
  UTC-offset deadlines, outcome-title references). Unknown keys,
  wrong types, missing required fields, and empty batches are
  contract violations — the guardrail never repairs. Acceptance
  stays with the deterministic acceptors, where the run/plan
  context lives. The companion guardrail, retry limits:
  `application/validated_generation.py` with
  `generate_validated_strategies/outcomes/tasks` — ask, parse,
  re-ask up to max_attempts (default 3), then propagate the last
  parse error chained; only the attempt that parses is recorded
  verbatim; ProviderCallError is not retried (that is TASK-103's
  fallback policy) and propagates untouched from the first attempt.
  The outcomes anchor rule moved to
  `domain/task_generation.plan_anchor`, shared by both task
  generation use cases. 30 tests (`tests/test_ai_validation.py`),
  including the full arc: provider → verbatim record → parsed
  proposals → `accept_proposed_tasks`.

- TASK-099 — Plan explanation (2026-09-16): docs/09's sixth AI
  operation — and the one where the record is the whole capability:
  unlike the five proposal operations there is no deterministic
  half to parse into, because the explanation is the product.
  `domain/plan_explanation.py` with the frozen
  `PlanExplanation(explanation_id, plan_id, snapshot_id, proposal,
  provider, model, created_at)` — the words verbatim (bounded at
  20k), tied to both the plan explained and the exact progress
  snapshot read (a fresh reading deserves a fresh explanation, and
  the audit trail must show which point in time was explained),
  with full provenance. `PlanExplanationRepository` port
  (insert-or-replace, get, list_for_plan earliest first). The use
  case, `application/plan_explanation.py`: `explain_plan(plan,
  tasks, snapshot, provider)` refuses a snapshot from another plan
  and wires the plan-and-progress context, the provider port, and
  the record; vendor faults propagate as ProviderCallError
  untouched. 15 tests (`tests/test_ai_plan_explanation.py`),
  including the fresh-snapshot-fresh-explanation arc.

- TASK-098 — Task generation (2026-09-16): the AI half of
  pipeline step 12 (docs/04). The deterministic half is
  `accept_proposed_tasks`, which binds TaskProposal batches to a
  living plan with resolved outcome-title references; this task adds
  the LLM side: `domain/task_generation.py` with the frozen
  `TaskGeneration(generation_id, plan_id, proposal, provider, model,
  created_at)` — the proposal verbatim (bounded at 20k), tied to the
  plan whose outcomes were decomposed (a generation is anchored to a
  single plan's shape), with full provenance; parsing into
  TaskProposal tuples is TASK-100's validation. `TaskGenerationRepository`
  port (insert-or-replace, get, list_for_plan earliest first). The
  use case, `application/task_generation.py`: `generate_tasks(outcomes,
  provider)` requires a non-empty outcome tuple sharing one plan,
  wires the outcomes-only context, the provider port, and the record;
  vendor faults propagate as ProviderCallError untouched. 17 tests
  (`tests/test_ai_task_generation.py`), including the seam to
  `accept_proposed_tasks`.

- TASK-097 — Outcome decomposition (2026-09-16): the AI half of
  pipeline step 11 (docs/04). The deterministic half is
  `define_outcome` binding an outcome to a plan; this task adds the
  LLM side: `domain/outcome_decomposition.py` with the frozen
  `OutcomeDecomposition(decomposition_id, goal_id, future_state_id,
  proposal, provider, model, created_at)` — the proposal verbatim
  (bounded at 20k), tied to both the goal and the exact future
  state it decomposes (a re-derived destination deserves a fresh
  decomposition, and the audit trail must show which one was read),
  with full provenance; parsing into outcome titles is TASK-100's
  validation. `OutcomeDecompositionRepository` port
  (insert-or-replace, get, list_for_future_state earliest first).
  The use case, `application/outcome_decomposition.py`:
  `decompose_outcomes(future, provider)` wires the
  future-state-only context, the provider port, and the record;
  vendor faults propagate as ProviderCallError untouched. 13 tests
  (`tests/test_ai_outcome_decomposition.py`), including the seam to
  `define_outcome`.

- TASK-096 — Strategy generation (2026-09-16): the AI half of
  pipeline step 8 (docs/04). The deterministic half has existed
  since EPIC-003 — `accept_proposed_strategies` binding proposals
  to a RUNNING run with unique names, `decide_strategy` selecting
  (step 9) — so this task adds the LLM side:
  `domain/strategy_generation.py` with the frozen
  `StrategyGeneration(generation_id, goal_id, proposal, provider,
  model, created_at)` — the proposal verbatim (bounded at 20k),
  tied to the goal, with full provenance; parsing into
  StrategyProposal tuples is TASK-100's validation, not the
  record's. `StrategyGenerationRepository` port (insert-or-replace,
  get, list_for_goal earliest first). The use case,
  `application/strategy_generation.py`: `generate_strategies(goal,
  state, future, provider)` wires the strategy context (the three
  anchors of every backcast), the provider port, and the record;
  vendor faults propagate as ProviderCallError untouched. 13 tests
  (in `tests/test_ai_strategy_generation.py`, alongside TASK-024's
  deterministic suite), including the seam test: a generation,
  read as name/rationale candidates, entering the existing
  acceptance through a real `calculate_gap`/`start_run` context —
  the two halves of step 8 provably meet.

- TASK-095 — Goal interpretation (2026-09-16): the first AI
  operation, wired end to end. `domain/goal_interpretation.py`
  with the frozen `GoalInterpretation(interpretation_id, goal_id,
  proposal, provider, model, created_at)` — the LLM's proposal kept
  verbatim (non-empty, bounded at 20k), tied to the goal it reads,
  carrying its provenance: which provider, which model (the one
  that answered, not the one requested), when. `record_goal_
  interpretation` helper and `interpretations_for_goal`
  (input-order filter). Like every observation, immutable — a
  re-interpretation is a new record. `GoalInterpretationRepository`
  port added to repositories.py (insert-or-replace by id, get,
  list_for_goal earliest first). The use case,
  `application/goal_interpretation.py`: `interpret_goal(goal,
  state, provider)` composes the context builder (goal + current
  state, nothing else), the provider port, and the record — and
  does nothing else: vendor faults propagate as ProviderCallError
  untouched (one currency for the TASK-103 fallback), persistence
  is the caller's wiring. 14 tests, including the reference
  in-memory fake for the port.

- TASK-094 — Context builder (2026-09-16): docs/09's context
  strategy, made structural. `application/context_builder.py` with
  frozen `ContextSection(heading, body)` rendered under `##`
  headings, `build_context(operation, sections, *, model?,
  max_output_tokens?, temperature?)` assembling one system message
  (the operation's fixed instruction from OPERATION_INSTRUCTIONS —
  all six of docs/09's operations, each ending with the ADR-002
  reminder "You propose; the system validates and enforces") and
  one user message (the sections in order, blank-line joined);
  unknown operations are rejected outright — a generic fallback
  instruction would silently produce the unspecific context the
  strategy forbids. Curated record renderers select fields, not
  records (ids and bookkeeping stay out): goal (title +
  description), current state (narrative), future state
  (description + target date), outcomes (bulleted), plan (title,
  workload, task list with durations or "no estimate yet"),
  progress (planned/worked/remaining/completed). The per-operation
  composers — goal interpretation and clarification (goal +
  current state), strategy (all three anchors), outcome
  decomposition (future only), task generation (outcomes only),
  explanation (plan + progress) — each take exactly the records
  their operation needs, so "do not resend full history" is a
  signature, not a convention. Output is a complete LLMRequest the
  operations hand straight to any vendor. 25 tests.

- TASK-093 — Google adapter (2026-09-16): the third vendor behind
  the LLM port, completing the adapter set. `infrastructure/
  google_provider.py` with `GoogleProvider(LLMProvider)` — name
  "google", the same lazy-import/injected-client construction as its
  siblings. Vendor-shape translation: neutral ASSISTANT turns are
  renamed to the vendor's "model" role; SYSTEM turns are hoisted
  into the config object's `system_instruction` (joined when
  multiple); a request of only system turns fails the call up front
  (no conversation to send); sampling knobs ride in the config, each
  only when the request set it — Gemini imposes no required output
  bound, so an unset one is simply absent. Response translation
  catches the vendor `text` property's own raise (safety refusal,
  empty candidates) and states it as provider trouble; usage crosses
  from usage_metadata (prompt/candidates token counts). Every vendor
  fault is ProviderCallError with the original exception chained.
  21 tests against a recording fake, closing with the three-vendor
  wiring: three API shapes, one port, callers that cannot tell the
  vendors apart except by name.

- TASK-092 — Anthropic adapter (2026-09-16): the second vendor
  behind the LLM port, over an API that differs in kind.
  `infrastructure/anthropic_provider.py` with
  `AnthropicProvider(LLMProvider)` — name "anthropic", the same
  lazy-import/injected-client/api-key-exclusive construction as the
  OpenAI adapter. Vendor-shape translation: neutral SYSTEM turns
  are hoisted out of the conversation into the vendor's top-level
  `system` parameter (multiple system turns joined blank-line
  separated; no system turn means no parameter); the vendor's
  required `max_tokens` is resolved from the request or the
  adapter's `default_max_output_tokens` (module default 1024,
  constructor-overridable) so the port's None-means-default holds;
  temperature passes through only when set — and is never clamped:
  the vendor's narrower 0–1 range rejects out-of-range values,
  which surface as ProviderCallError rather than a silently
  changed proposal. Response translation joins the text blocks'
  text (non-text blocks skipped), records the model that answered,
  maps input/output tokens to prompt/completion. Every vendor
  fault — including no text blocks and a missing model — is
  ProviderCallError with the original exception chained. 23 tests
  against a recording fake, including the side-by-side wiring:
  two vendors, one interface, indistinguishable except by name.

- TASK-091 — OpenAI adapter (2026-09-16): the first vendor behind
  the LLM port. `infrastructure/openai_provider.py` with
  `OpenAIProvider(LLMProvider)` — name "openai", injected SDK client
  (or lazy default client, optionally with an explicit api_key;
  never both) and a `default_model` resolving the neutral request's
  None-means-provider-default. Translation out: neutral Message
  turns become vendor chat messages verbatim, `max_output_tokens`
  crosses as `max_completion_tokens`, temperature passes through,
  and unset knobs stay out of the vendor call entirely. Translation
  back: content, the model that actually answered, and the usage
  counts when present. Every vendor fault — connection, auth,
  timeout, empty choices, unusable content, missing model, absent
  SDK — surfaces as `ProviderCallError` with the original exception
  chained, so the fallback logic (TASK-103) sees one currency; the
  SDK imports lazily so wiring the adapter never requires the
  package. 18 tests against an injected fake client — no network,
  no SDK, no secrets.

- TASK-090 — LLM provider interface (2026-09-16): the AI boundary
  port of docs/09 and ADR-006. `domain/llm_provider.py` with the
  neutral conversation vocabulary — `MessageRole` (system/user/
  assistant), frozen `Message` (non-empty, bounded) — frozen
  `LLMRequest(operation, messages, model?, max_output_tokens?,
  temperature?)` where the operation is mandatory (the audit log and
  permission checks key on it) and every vendor knob is optional
  None-means-provider-default, and frozen `LLMResponse(content,
  model, prompt_tokens?, completion_tokens?)` where the model that
  actually answered is recorded, not the one requested. The
  `LLMProvider` ABC: abstract `name` (identity for audit and
  fallback routing) and abstract `complete(request) -> response`.
  Two failure currencies, mirroring repositories.py: bad requests
  and malformed responses raise `LLMProviderError` (programming
  errors), vendor/transport failures raise `ProviderCallError`
  (the single type the TASK-103 fallback will catch) so callers
  never see SDK-specific exceptions. No tools, streaming, or
  multimodality — the six text operations of docs/09 need none of
  it, and the tool-permission guardrail arrives as TASK-101.
  22 tests, including a reference EchoProvider pinning the contract
  and an AST-level assertion that the module imports stdlib only.

- TASK-089 — Replanning integration (2026-09-16): the epic-closing
  suite (`tests/test_replanning_integration.py`) pinning EPIC-009 end
  to end over one realistic situation. The automatic arc: cumulative
  weekly progress snapshots -> progress variance -> shortfall
  magnitudes -> threshold -> persistence -> triggers on record
  (progress behind, evenings worked) -> policy -> decision (ACT
  REPLAN) -> global re-derivation -> `compare_plans` adoption under
  shared buffer/capacity -> the version trail. The stability
  branches: one slow-then-recovered week resets the run and decides
  nothing; hysteresis holds through a dip into the gap; a re-confirmed
  condition waits out its cooldown. The other modes: SUGGEST proposes
  (minimum-change picks REPLAN over goal revision; the goal revision
  itself is only ever proposed), MANUAL holds. The overwork arc runs
  the same machinery in the other direction: sustainability's
  arithmetic against the declared windows, the utilization adapter
  feeding the same threshold vocabulary, the behavior trigger on
  record, and a suggestion rather than an act — the pace is the
  user's. 7 tests, no new product code — the composition is the
  capability. EPIC-009 complete.

- TASK-088 — Plan comparison (2026-09-16): current vs candidate,
  mechanically. `domain/plan_comparison.py` with `PreferredPlan`
  (CURRENT/CANDIDATE), the frozen `PlanComparison(current,
  candidate, both FeasibilityResults, workload_delta, preferred,
  reason)` — candidate must be another version of the same plan —
  and `compare_plans(current, candidate, *, buffer,
  usable_capacity)`: both sides judged under the same buffer and
  capacity so the comparison is honest. The rules, all from the
  spec's own: feasibility first (docs/04's rule is authoritative —
  a feasible plan beats an infeasible one, whichever side); with
  verdicts equal, the candidate wins only on strictly more slack
  (same destination, cheaper path — level 2 fixes the
  Goal/Future); a tie keeps the current plan (minimum-change:
  adopting a no-gain candidate is change for its own sake). The
  arithmetic is stated alongside the verdict so the reasoning
  layer can disagree with grounds; what the domain deliberately
  does not weigh — strategic fit, preference, risk — stays with
  the LLM and the user (ADR-002). 12 tests, including the global
  replan candidate (20h declared, 9h re-derived) adopted under
  12h capacity.

## Notes
- This file is historical. Keep the current state in `PROJECT_STATE.json`.
