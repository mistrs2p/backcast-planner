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
- Initial execution pack created.
