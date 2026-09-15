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
- Initial execution pack created.
