# scripts — Repository Scripts

Development, validation, and automation scripts for the repository.

- `check_rules.py` — AGENTS.md rule enforcement (TASK-002): validates AGENTS.md
  structure, rejects tracked secret files and non-placeholder credentials in
  `.env.example`, and enforces domain-layer import purity under `apps/api`.
  Run with `python scripts/check_rules.py`; exit code 1 reports violations.

- `project_state.py` — PROJECT_STATE foundation (TASK-003): validates the
  PROJECT_STATE.json schema (required keys, lifecycle enums, validation results,
  ISO dates) and its consistency with `tasks/TASK-MANIFEST.json` and task-file
  statuses. Run with `python scripts/project_state.py validate`.

- `progress.py` — Progress system foundation (TASK-004): `report` aggregates
  task statuses per epic from the manifest and task files; `check` detects
  drift between docs/PROGRESS.md and PROJECT_STATE.json.

- `git_workflow.py` — Git workflow foundation (TASK-005): `check-branch`
  enforces task-branch naming and rejects protected branches;
  `check-commits` validates Conventional Commit style for non-merge commits.

Scripts for CI support (TASK-006) will be added by their respective tasks.
