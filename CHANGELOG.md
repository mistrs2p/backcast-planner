# Changelog

## Unreleased

- Repository bootstrap: execution pack committed, monorepo skeleton materialized
  (`apps/`, `packages/contracts/`, `infra/`, `scripts/`, `tests/`), pytest harness
  and repository-structure tests added (TASK-001).
- AGENTS.md enforcement: `scripts/check_rules.py` validates AGENTS.md structure,
  rejects tracked secrets and non-placeholder credentials, and enforces domain-layer
  import purity; covered by enforcement tests (TASK-002).
- PROJECT_STATE foundation: `scripts/project_state.py` validates the state schema and
  cross-checks it against the task manifest and task statuses; stale TASK-003/TASK-009
  version-verification references corrected (TASK-003).
- Progress system foundation: `scripts/progress.py` reports backlog status per
  epic and checks docs/PROGRESS.md stays synchronized with PROJECT_STATE.json (TASK-004).
- Git workflow foundation: `scripts/git_workflow.py` enforces task-branch naming,
  rejects development on protected branches, and validates Conventional Commit
  messages (TASK-005).
- CI baseline: GitHub Actions workflow runs the test suite and all repository
  validators on pushes/PRs to main; `requirements-dev.txt` added (TASK-006).
- Docker baseline: `infra/docker-compose.yml` provides PostgreSQL 18 + Redis with
  health checks and persistent storage for local development (TASK-007).
- Environment configuration: validated stdlib-only `Settings` layer for the backend
  (`apps/api/src/backcasting/config.py`) with optional `.env` seeding (TASK-008).
- Technology verification: exact versions verified against official sources and
  recorded in ADR-007; backend dependencies, dev dependencies, and Docker images
  exactly pinned with traceability tests (TASK-009).
- Shared contracts foundation: FastAPI application factory with /health,
  OpenAPI contract generated and committed to packages/contracts with CI drift
  checking (ADR-008); test client moved to httpx2 (TASK-010).
- User domain model: `Email` value object and immutable `User` entity with
  validated IANA timezone and UTC timestamps; `tzdata` added as a runtime
  dependency for `zoneinfo` portability (TASK-011).
- Goal domain model: immutable `Goal` entity with user ownership, the six
  spec lifecycle states (DRAFT → ACTIVE → PAUSED → COMPLETED/CANCELLED/
  ARCHIVED), and create/revise factories; lifecycle transition rules
  deferred to the goal-lifecycle task (TASK-012).
- Current State domain model: immutable per-goal snapshot of present reality
  with UTC capture time; snapshots accumulate for replanning instead of
  mutating (TASK-013).
- Future State domain model: immutable destination with a UTC target date
  anchored after creation; changed only through explicit revision per the
  replanning model (TASK-014).
- Metric abstraction: five measurement kinds with per-kind validation,
  maximize/minimize/target directions, and direction-aware variance
  interpretation (TASK-015).
- Goal lifecycle: transition table enforcing DRAFT → ACTIVE, pause/resume,
  and terminal finality (COMPLETED/CANCELLED/ARCHIVED) with
  InvalidGoalTransition on illegal moves (TASK-016).
- Domain validation: cross-entity rules for a goal's assembled context
  (ownership matching, target-after-snapshot) with aggregated issue
  reporting — the deterministic validation seam required by the AI
  architecture (TASK-017).
- Domain events: immutable typed event envelope with read-only payloads,
  an in-memory collector, and constructors for current domain operations;
  publication deferred to infrastructure (TASK-018).
- Repository interfaces: abstract persistence ports for User, Goal,
  Current State, and Future State — insert-or-replace by identity with
  ordering guarantees; the domain stays free of ORM imports (TASK-019).
- Gap model: the distance between a current state and a future state as
  validated metric dimensions with an optional narrative (TASK-020).
- Gap calculation: deterministic service that validates the goal context
  before recording a gap from (metric, current, target) measurements
  (TASK-021).
- Backcasting run: record of one pipeline execution per goal with exact
  input references (goal, snapshot, destination, gap), a one-shot
  RUNNING → COMPLETED/FAILED lifecycle, and gap-provenance guards
  (TASK-022).
- Strategy model: candidate strategies bound to a running backcasting
  run with a one-shot CANDIDATE → SELECTED/REJECTED decision lifecycle
  (TASK-023).
- Strategy generation: deterministic acceptance of AI-proposed strategy
  batches as run candidates — non-empty, unique names, running run only
  (TASK-024).
- Feasibility engine: required workload + buffer ≤ usable capacity over
  non-negative timedeltas, with signed slack exposed (TASK-025).
- Milestone model: intermediate measurable checkpoint bound to a running
  backcasting run, with a target date strictly after creation and no
  lifecycle of its own — achievement flows through outcomes (TASK-026).
- Milestone generation: deterministic acceptance of AI-proposed milestone
  batches — unique titles, strictly increasing target dates strictly
  inside the acceptance-to-destination window, exact destination
  provenance (TASK-027).
- Backcasting integration: `execute_backcasting` orchestrates the
  deterministic pipeline (gap → feasibility → strategies → selection →
  milestones) with one-shot run semantics; failures carry the FAILED run
  and the failing step (TASK-028). EPIC-003 complete.
- Calendar model: user-owned calendar root with a ZoneInfo home timezone
  and the 15-minute MVP planning granularity pinned as a constant
  (TASK-029).
- Calendar event: time-blocked entry with UTC start/end (end > start),
  deliberately unaligned to planning granularity and task-free — an
  event is not necessarily a task (TASK-030).
- Recurrence rules: DAILY/WEEKLY patterns with intervals and weekday
  sets expanding deterministically into calendar events, preserving
  local time of day across DST transitions (TASK-031).
- Recurrence exceptions: occurrences addressed by original start —
  cancelled or rescheduled (optionally re-durationed) — applied
  deterministically over a rule's expansion (TASK-032).
- Floating rest: weekday-free weekly rest quota with satisfaction
  measured from arbitrary intervals, overlaps merged so rest time is
  never double-counted (TASK-033).
- Availability windows: weekly wall-clock patterns on a calendar
  expanding into UTC intervals over a range — DST-aware local times,
  clipped to the range (TASK-034).
- Timezone handling: shared `domain/timezone.py` for the mandatory
  semantics — UTC-instant validation, wall-clock conversion across DST
  (fold-aware), local-time classification (unambiguous/ambiguous/
  nonexistent), and Monday-anchored week bounds; duplicated per-module
  UTC checks consolidated onto it (TASK-035).
- Calendar conflict detection: deterministic overlap sweep over a
  calendar's events reporting each clashing pair once with its shared
  interval; touching events do not conflict. Fixed latent
  `timezone`-parameter shadowing that crashed the default clock in
  `create_calendar`, `create_rule`, and `create_availability_window`
  when `created_at` was omitted (TASK-036).
- Calendar API: first HTTP surface — layered as Presentation →
  Application → Domain → Infrastructure. Calendar/event repository
  ports in the domain, a `CalendarService` use-case layer, thread-safe
  in-memory repositories until the production persistence epic, and
  REST endpoints for calendars, events, and conflict detection (404/409
  /422 mapping, UTC normalization on input). OpenAPI contract
  regenerated (TASK-037).
- Planned capacity: the workable time over a period — availability
  windows merged (DST-aware, clipped to the period) minus the existing
  commitments occupying them, recorded per calendar as an immutable
  `PlannedCapacity` (TASK-038).
- Initial execution pack created.
