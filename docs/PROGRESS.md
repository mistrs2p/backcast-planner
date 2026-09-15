# Project Progress

## Current
- Phase: Implementation
- Current Task: TASK-056 (Plan validation)
- Current Epic: EPIC-006 Planning

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

## Notes
- This file is historical. Keep the current state in `PROJECT_STATE.json`.
