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
- Initial execution pack created.
