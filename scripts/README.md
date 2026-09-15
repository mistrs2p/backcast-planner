# scripts — Repository Scripts

Development, validation, and automation scripts for the repository.

- `check_rules.py` — AGENTS.md rule enforcement (TASK-002): validates AGENTS.md
  structure, rejects tracked secret files and non-placeholder credentials in
  `.env.example`, and enforces domain-layer import purity under `apps/api`.
  Run with `python scripts/check_rules.py`; exit code 1 reports violations.

Scripts for PROJECT_STATE validation (TASK-003), progress system maintenance
(TASK-004), and CI support (TASK-006) will be added by their respective tasks.
