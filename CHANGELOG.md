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
- Observed capacity: the backward-looking measurement of the same
  semantics over a period that has ended (`measured_at ≥ period_end`),
  an immutable historical fact with no revision path; the computation
  is shared via `workable_time` (TASK-039).
- Effective capacity: the usable capacity for the feasibility rule —
  the plan adjusted by the aggregate observed/planned ratio of
  `CapacitySample` history, with cold-start and zero-plan fallbacks;
  uncapped, since conservatism is the buffer's job (TASK-040).
- Capacity pool: the split of a period's effective capacity across
  goals — unique-goal allocations that never exceed the pool, with the
  remainder left unallocated for the scheduler (TASK-041).
- Constraints: hard scheduling restrictions — fixed blocked UTC ranges
  and weekly wall-clock exclusions (DST-aware), with blocked-interval
  expansion and half-open overlap checking (TASK-042).
- Preferences: the soft scheduling layer — weekly wall-clock windows
  with a `PREFER`/`AVOID` direction and a 1–5 weight; DST-aware
  window expansion and a boolean applicability check (a preference
  ranks candidates, it never rejects a slot) (TASK-043).
- Buffer: the conservatism layer of feasibility — a per-period
  fraction of usable capacity held in reserve (0 ≤ ratio < 1), with
  reserved/usable computation and `apply_buffer` pairing a buffer
  with the matching effective-capacity record (TASK-044).
- Capacity analysis: pipeline step 5 — `analyze_time_environment`
  composes availability, constraints, commitments, history, and buffer
  into the `CapacityAnalysis` record whose `usable_amount` feeds the
  feasibility rule (TASK-045).
- Plan model: the executable shape of a goal — workload, optional
  run provenance, the DRAFT/CANDIDATE → ACTIVE →
  SUPERSEDED/ARCHIVED/INVALID lifecycle, routine revision, and the
  max-one-active-plan-per-goal rule (TASK-047).
- Plan versioning: traceable replan history — per-plan strictly
  increasing versions with reason, source-run provenance, and a
  content change set; no-op replans rejected (TASK-048).
- Outcome model: the "achieved state/result" — plan-owned, optionally
  milestone-bound, taskless by design, with descriptive-only revision
  (TASK-049).
- Task model: the "actionable unit of work" — plan-owned, optionally
  deadlined, schedulable only with a duration, outcome links kept
  inside one plan (TASK-050).
- Task dependencies: finish-to-start links with write-time cycle,
  duplicate, self, and cross-plan rejection; direct/transitive
  prerequisite queries and a deterministic topological order
  (TASK-051).
- Resources: standalone catalog entities linked to tasks through an
  idempotent N:M requirement (`resource_ids` on Task) (TASK-052).
- Task estimation: append-only estimate records with provenance and
  rationale, validated application onto the owning task, and a
  workload sum that refuses unestimated tasks (TASK-053).
- Task decomposition contract: `TaskProposal` and
  `accept_proposed_tasks` — the AI-proposes/domain-validates boundary
  for pipeline step 12, with plan-liveness, outcome-resolution, and
  batch-uniqueness rules (TASK-054).
- Plan generation: `begin_plan` opens a run-provenanced DRAFT from a
  COMPLETED run; `publish_plan` closes it into a CANDIDATE with the
  workload computed from task estimates (TASK-055).
- Plan validation: whole-plan gate before activation — ownership,
  estimation, workload drift, dependency health, and feasibility
  issues returned together; `activate_plan` enforces CANDIDATE-only
  promotion and the max-one-active-plan rule (TASK-056).
- Candidate slot generation: maximal free intervals (merged
  availability minus in-window commitments) a task of a given
  duration fits into — the raw material the scheduling hierarchy
  filters and ranks (TASK-057).
- Hard constraint filtering: constraints subtract their blocked
  intervals from candidate slots, keeping only pieces that still fit
  the task's duration (TASK-058).
- Capacity filtering: the goal's remaining budget gates the task
  (NO_CAPACITY when it cannot hold the duration) and slots are
  clipped to the analyzed-capacity period (TASK-059).
- Dependency filtering: finish-to-start as slot arithmetic — slots
  clip to the last direct prerequisite's finish; an unplaced
  prerequisite blocks the task (DEPENDENCY_BLOCKED) (TASK-060).
- Deadline handling: slots clip their ends to the task's deadline —
  finishing exactly at it is on time, shorter remainders drop, and an
  emptied list is the DEADLINE_CONFLICT fact (TASK-061).
- Preference scoring: the soft layer — each preference contributes
  ±weight × overlap fraction and slots rank best-first without ever
  being rejected; ties keep chronological order (TASK-062).
- Task splitting: the placement fallback — a duration no single slot
  holds flows greedily through the ranked slots in 15-minute
  granularity multiples; parts sum exactly, insufficient capacity
  returns empty (NO_AVAILABLE_SLOT) (TASK-063).
- Schedule persistence: the placement record — `Schedule` +
  `place_task` (deadline-respecting, non-overlapping per task) and
  the `ScheduleRepository` port (TASK-064).
- Conflict resolution: commitments displace placements, the
  later-starting placement yields between placements, and a displaced
  task with no surviving candidates escalates to replanning
  (docs/06 principle) (TASK-065).
- Rescheduling: level 1 of the adaptation ladder — displaced
  placements withdraw and the same workload re-places into fresh
  allocations; kept placements stay put, workload preserved to the
  tick (docs/08) (TASK-066).
- Rolling horizon: the two-week operational window (docs/06) and the
  exact/approximate split — due tasks, near-milestone outcome tasks,
  and their prerequisite chains go to exact scheduling (TASK-067).
- Scheduler integration: the full chain composed per task in
  dependency order — candidates, constraints, capacity, dependencies,
  deadline, preferences, splitting, placement — with docs/06 failure
  reasons surfacing at the layer that caused them and the budget
  consumed in order; EPIC-007 complete (TASK-068).
- Execution model: the Actual of "Planned ≠ Actual ≠ Progress" —
  one record per sitting, facts recorded without deadline judgment
  or rounding, summed by actual_duration (TASK-069).
- Measurement model: observed data for a metric — one validated,
  immutable value per observation, attached to an optional milestone
  or outcome subject, queryable per subject and by latest reading;
  MeasurementRepository port added (TASK-070).
- Progress snapshots: the derived third term of "Planned ≠ Actual ≠
  Progress" — one immutable point-in-time reading per plan with
  planned/actual/remaining workload, progress and completion rate
  capped at done (overruns belong to variance); per-task completion;
  ProgressSnapshotRepository port added (TASK-071).
- Velocity: the observed work rate over a calendar window — sittings
  clipped to the window edges, a dimensionless rate plus a per-day
  timedelta for projections (TASK-072).
- Variance signals: the four time-denominated planned-vs-actual
  differences — progress, time, capacity, schedule — one record with
  a single sign convention and inherent favorability per kind
  (TASK-073).
- Capacity integration tests: the epic-closing suite wiring recurrence
  and exceptions into the capacity chain and on into
  `execute_backcasting` — feasible and infeasible end-to-end paths,
  DST capacity loss, and pool splitting (TASK-046).
- Initial execution pack created.
