# apps/api — Backend (FastAPI)

FastAPI modular monolith implementing the deterministic domain core and the
application/API layers of the Backcasting Goal & Adaptive Planning System.

Planned layering (see `docs/10-TECHNICAL-ARCHITECTURE.md`):

```
Presentation (API routes, contracts) → Application (use cases) → Domain (pure logic) → Infrastructure (persistence, LLM providers)
```

Rules:

- The domain layer must not import FastAPI, SQLAlchemy, Redis, vendor LLM SDKs,
  or UI libraries (`AGENTS.md` §4).
- LLM output is untrusted input; the LLM never directly mutates the database
  (`AGENTS.md` §5).
- Database changes require Alembic migrations.

Current contents: `src/backcasting/config.py` — the validated environment
configuration layer (TASK-008). Dependency manifests and Docker wiring are
introduced by subsequent EPIC-001 tasks (technology verification, Docker
services).
