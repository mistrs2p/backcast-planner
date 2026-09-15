# ADR-008: OpenAPI as the shared API contract

## Status

Accepted (2026-09-15, TASK-010 — Shared contracts foundation)

## Context

`docs/10-TECHNICAL-ARCHITECTURE.md` requires that "the API exposes use cases
and generated contracts". The repository has a Python/FastAPI backend
(`apps/api`) and a TypeScript/Next.js frontend (`apps/web`), so both sides
need an agreed contract format that stays synchronized as the API evolves.

Options considered:

1. **Hand-written shared schema package** (e.g. JSON Schema or protobuf files
   authored in `packages/contracts` and consumed by both sides).
2. **OpenAPI generated from the backend** — FastAPI derives the schema from
   the actual route/pydantic definitions; the generated document is committed
   to `packages/contracts` and the frontend derives typed clients from it.
3. **TypeScript-first contracts** with backend codegen — inverts the natural
   direction, since the API is defined by the backend's use cases.

## Decision

**Option 2: the FastAPI application is the single source of truth for the
API contract.** `scripts/generate_contracts.py` exports
`create_app().openapi()` to `packages/contracts/openapi.json`, which is
committed and versioned like any other source file. `--check` mode fails
when the committed artifact drifts from the application, and CI runs that
check (TASK-006 pipeline), so contract changes are always deliberate,
reviewable commits.

Consequences:

- The contract cannot lie: it is structurally derived from the routes and
  request/response models that actually run.
- Frontend typing (e.g. via `openapi-typescript` or similar) is generated
  from the committed artifact when the web app is scaffolded; no TypeScript
  contract tooling is introduced before there is a web app to consume it.
- Breaking API changes surface as reviewable diffs in `openapi.json`.
- The application factory (`backcasting.app.create_app`) is the stable
  generation entry point; all future routes must be registered through it.

## Initial contract surface

The first generated contract exposes `GET /health` (operation `getHealth`)
as the liveness signal. Subsequent tasks extend the application and
regenerate the contract in the same commit that adds the routes.

## Relationship to other decisions

- Versions of the tools involved are pinned by ADR-007.
- Deterministic domain behavior stays authoritative (ADR-002); the contract
  only describes the API surface, not domain rules.
