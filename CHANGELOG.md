# Changelog

## Unreleased

- Repository bootstrap: execution pack committed, monorepo skeleton materialized
  (`apps/`, `packages/contracts/`, `infra/`, `scripts/`, `tests/`), pytest harness
  and repository-structure tests added (TASK-001).
- AGENTS.md enforcement: `scripts/check_rules.py` validates AGENTS.md structure,
  rejects tracked secrets and non-placeholder credentials, and enforces domain-layer
  import purity; covered by enforcement tests (TASK-002).
- Initial execution pack created.
