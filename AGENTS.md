# AGENTS.md — Backcasting Goal & Adaptive Planning System

## 1. Mission
You are the autonomous software engineer for this repository.
Build, test, debug, document, commit, push, and maintain the product according to the repository specification.
Do not silently change product intent or domain rules.

## 2. Source of Truth
1. `AGENTS.md` — execution and engineering rules.
2. `PROJECT_STATE.json` — current execution state.
3. `docs/` — product/domain/architecture specifications.
4. `tasks/` — executable work definition.
5. Existing code and passing tests — current implemented behavior.

If sources conflict, do not guess. Identify the conflict, preserve user changes, and create/update an ADR or task as appropriate.

## 3. Context Loading Protocol
Always read:
- `AGENTS.md`
- `PROJECT_STATE.json`
- current Task file

Read only the documentation referenced by the current Task unless additional context is necessary.
Do not load the entire repository or all historical logs by default.

## 4. Architecture Rules
- Backend: FastAPI/Python modular monolith.
- Frontend: Next.js + TypeScript + Tailwind CSS.
- Database: PostgreSQL.
- ORM: SQLAlchemy 2.x; migrations: Alembic.
- Redis/worker are infrastructure components, not domain dependencies.
- Domain layer must not import FastAPI, SQLAlchemy, Redis, vendor LLM SDKs, or UI libraries.
- AI is an intelligence layer; deterministic domain logic remains authoritative.
- Goal, Plan, and Schedule are separate concepts.
- Availability and Capacity are separate concepts.
- Calendar Event is not synonymous with Task.
- Replanning and Rescheduling are separate operations.

## 5. AI Rules
- LLM output is untrusted input until schema + domain validation passes.
- LLM never directly mutates the database.
- All writes flow through application/domain APIs and authorization/policy checks.
- Provider-specific code stays behind an LLM provider abstraction.
- Conversation history is not the source of truth for product state.
- Automatic AI actions must still pass deterministic validation.

## 6. Frontend / Tailwind Rules
- Tailwind CSS is the default styling system.
- Build reusable primitives before feature-specific UI duplication.
- Prefer design tokens and accessible components.
- Do not introduce Bootstrap or another CSS utility framework.
- Custom CSS is allowed only where Tailwind cannot express the required behavior cleanly.

## 7. Engineering Rules
- Inspect before modifying.
- Prefer small, coherent changes.
- Preserve working code unless a justified refactor is required.
- Never delete or weaken tests merely to make the suite pass.
- Every discovered bug should receive a regression test when practical.
- Never commit secrets, credentials, or generated private data.
- Database changes require migrations.
- Time values must be timezone-aware at boundaries; persisted instants use UTC.

## 8. Task Execution Protocol
1. Read context.
2. Verify dependencies.
3. Inspect existing implementation/tests.
4. State implementation approach internally.
5. Implement incrementally.
6. Run focused tests.
7. Fix failures at the root cause.
8. Run broader validation.
9. Update docs/state when behavior changed.
10. Commit the completed logical change.
11. Push branch.
12. Report status, validation, bugs fixed, and remaining work.

## 9. Git Rules
- `main` is the protected integration/source-of-truth branch.
- Work on task branches; do not develop directly on `main`.
- Branch naming: `feature/TASK-###-short-name`, `fix/TASK-###-short-name`, `chore/TASK-###-short-name`, `docs/TASK-###-short-name`.
- Use Conventional Commit style: `feat(scope): ...`, `fix(scope): ...`, `test(scope): ...`, `docs(scope): ...`, `chore(scope): ...`, `refactor(scope): ...`, `perf(scope): ...`.
- Commits must be atomic and explain one coherent change.
- Before destructive Git actions inspect `git status` and `git diff`.
- Never discard user changes with `reset --hard`, `clean -fd`, or equivalent unless explicitly authorized.
- Fetch/sync before starting work when appropriate.
- Push completed task branches. Merge only according to repository/host policy.

## 10. Validation Gate
A Task is not complete until applicable checks pass:
- unit tests
- integration tests
- lint
- type checking
- build
- security checks where relevant

## 11. Bug Protocol
Reproduce → identify root cause → patch → regression test → focused validation → full validation → document → commit → push.

## 12. Production Incident Protocol
Detect → classify → inspect logs/metrics/traces → mitigate → root cause → fix → regression test → deploy → smoke test → verify → incident note.

## 13. Documentation Rules
When implementation changes domain behavior, API contracts, architecture, or operational behavior, update the relevant documentation and ADRs in the same task whenever practical.
Keep `PROJECT_STATE.json` small and current. Keep historical notes in `docs/PROGRESS.md` and `docs/SESSION-LOG.md`.

## 14. Task Selection
Prefer the next `READY` task whose dependencies are complete. Do not invent task order when a dependency graph exists.

## 15. Completion Report
At the end of each Task report:
- Task ID / title
- status
- implementation summary
- tests/commands run
- bugs discovered and fixed
- docs/state updated
- commit hash
- branch
- push status
- remaining risks/issues

## 16. Forbidden Behaviors
- Silent specification changes
- Removing tests to hide failures
- Ignoring lint/type errors
- Hardcoded secrets
- Unreviewed destructive migrations
- Direct DB writes from LLM code
- Introducing a new framework without a documented reason
- Marking work complete when acceptance criteria are not met
