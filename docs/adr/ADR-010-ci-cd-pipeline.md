# ADR-010: CI/CD pipeline

Date: 2026-09-16
Status: Accepted
Task: TASK-118

## Context

docs/10-TECHNICAL-ARCHITECTURE.md requires "production adds CI/CD,
observability, backups, rollback and smoke tests", and docs/14's
pipeline starts "validate → build → …". TASK-006 delivered a CI
baseline: one GitHub Actions workflow running the backend suite and
the repository validators. Since then two whole gate families
appeared that the baseline does not run: the web gates
(`npm run verify` — shell, design and type checks — plus
`npm run build`) and the Docker artifacts from TASK-117
(`scripts/check_docker.py` plus the images themselves).

## Decision

1. **The TASK-006 workflow is extended, not replaced.** One
   `ci.yml`, three parallel jobs: `validate` (backend suite,
   contract drift, rules, state, progress, docker artifact checks,
   CI workflow checks, conventional commits on PRs), `web` (verify
   + build on pinned Node 22 — the version the production image
   runs), and `docker` (`docker compose build`, exercising both
   Dockerfiles exactly as the local environment does). Every
   AGENTS.md validation gate now runs on every push and pull
   request to main; a change that breaks the web build or the
   images fails CI, not deploy time.

2. **The workflow's shape is pinned statically.**
   `scripts/check_ci.py` checks the same class of invariants as
   `scripts/check_rules.py` and `scripts/check_docker.py`: the
   triggers (push/PR to main — the protected integration branch),
   the three jobs, the commands each must run, the pinned Node
   version, and the absence of credential keys. A gate that
   quietly disappears from the workflow is a hole in the pipeline
   nothing else catches. The script runs inside `validate`, so the
   workflow validates itself on every run.

3. **CD stops at proven buildability — deliberately.** CI builds
   the images but does not push them to a registry and does not
   deploy. There is no production target or registry credential in
   the repository (and per AGENTS.md none may be tracked), and
   ADR-009's decision to bake `API_ORIGIN` into the web image means
   a published image is environment-specific anyway. This supersedes
   ADR-009's expectation that "a multi-environment registry flow
   arrives with CI/CD (TASK-118)": the flow arrives with the tasks
   that own it — TASK-128 (production deployment) and TASK-132
   (release tagging) — where a real target and the tagging policy
   exist.

## Consequences

- CI runtime grows: three jobs run in parallel, so wall-clock cost
  is the longest job, but runner minutes increase. Acceptable at
  this scale.
- The `docker` job builds but never runs the containers; runtime
  behavior stays covered by the live `docker compose up --build`
  validation documented in docs/PROGRESS.md for TASK-117, and later
  by the smoke-test task (TASK-129).
- Local parity: the per-task validation gate now includes
  `python scripts/check_docker.py` and `python scripts/check_ci.py`
  alongside the TASK-006 validators, matching what CI enforces.
