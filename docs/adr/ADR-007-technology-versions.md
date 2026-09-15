# ADR-007: Verified technology baseline versions

## Status

Accepted (2026-09-15, TASK-009 — Technology verification)

## Context

The technology baseline (`README.md`, `PROJECT_STATE.json`) named major
versions (Next.js 16.x, Tailwind CSS 4.x, FastAPI 0.141.x, PostgreSQL 18.x,
SQLAlchemy 2.x, Alembic) without exact pins. TASK-009 requires verifying exact
current versions and compatibility using official project sources, recording
selected versions, security notes, breaking changes, and rationale — and
explicitly warns against choosing dependencies solely because they have the
highest version number.

## Verification sources (all queried 2026-09-15)

- Python packages: PyPI (`pip index versions`) — fastapi 0.141.1, uvicorn
  0.53.0, sqlalchemy 2.0.53, alembic 1.20.0, psycopg 3.3.5, redis 8.1.0,
  pytest 9.1.1, pyyaml 6.0.3, httpx2 2.13.0 (added by TASK-010 for FastAPI's
  TestClient; starlette 1.6.0 deprecates the original httpx for TestClient,
  so the httpx2 line is the forward-compatible choice).
- Node packages: npm registry (`registry.npmjs.org`) — next 16.3.5,
  react 19.3.0, tailwindcss 4.3.3, typescript latest = 7.0.2, newest 5.x =
  5.9.3 (5.9.4+ do not exist).
- Node.js runtime: `nodejs.org/dist/index.json` — Node 24.21.0 "Krypton" is
  the current LTS line; Node 22.23.2 "Jod" remains in maintenance.
- Containers: Docker Hub + `docker run --version` — `postgres:18` currently
  ships PostgreSQL 18.4; `redis:7-alpine` currently ships Redis 7.4.11.
  Exact tags `postgres:18.4` and `redis:7.4.11-alpine` exist on Docker Hub.
- Next.js compatibility: `next@16.3.5` package metadata — requires
  Node `>=20.9.0`, react/react-dom `^18.2.0 || ^19.0.0`, no TypeScript peer
  requirement.

## Decision

### Backend (apps/api, pinned in `apps/api/pyproject.toml`)

| Component | Version | Rationale |
|---|---|---|
| Python | 3.12 | Verified locally and in CI; conservative over newer 3.x until app deps are exercised on them. |
| fastapi | 0.141.1 | Matches the baseline's 0.141.x line; latest patch. |
| uvicorn[standard] | 0.53.0 | Standard ASGI server for FastAPI; latest. |
| sqlalchemy | 2.0.53 | Baseline mandates 2.x; latest 2.0 patch keeps bug/security fixes. |
| alembic | 1.20.0 | Migration tool per baseline; latest. |
| psycopg[binary] | 3.3.5 | psycopg 3 (not legacy psycopg2) — matches the `postgresql+psycopg://` URLs already used in `.env.example` and infra. |
| redis | 8.1.0 | Official Python client for Redis. |
| tzdata | 2026.4 | IANA timezone database for the stdlib `zoneinfo` module. Required on Windows (no system tz database) and the portable fallback elsewhere; added by TASK-011 when the User model introduced `ZoneInfo` validation. |

### Frontend (recorded; manifests land with the web scaffold)

| Component | Version | Rationale |
|---|---|---|
| next | 16.3.5 | Baseline 16.x; latest patch. |
| react / react-dom | 19.3.0 | Satisfies next@16 peers (`^19.0.0`); latest stable. |
| tailwindcss | 4.3.3 | Baseline 4.x; latest patch. |
| typescript | 5.9.3 | **Deliberately not the highest.** TypeScript 7.0.2 (the native-compiler line) is `latest` on npm, but next@16's toolchain predates it and no official Next.js↔TS7 compatibility statement is pinned here. 5.9.3 is the newest release of the 5.x line the Next 16 ecosystem was built against. Revisit when Next documents TS 7 support. |
| Node.js | 24 LTS (24.21.0) | Active LTS line; satisfies next@16 `>=20.9.0`. |

### Infrastructure

| Component | Version | Rationale |
|---|---|---|
| PostgreSQL | 18.4 (`postgres:18.4`) | Baseline 18.x; current patch. Note: the 18 image requires the volume mount at `/var/lib/postgresql` (see TASK-007). |
| Redis | 7.4.11 (`redis:7.4.11-alpine`) | Mature 7.x line; verified running in the compose smoke test. Redis 8.x exists but brings module/licensing churn with no current need — revisit when a feature requires it. |

### Deferred decision: worker framework

The baseline allows "Redis + worker for asynchronous work when justified".
The Redis client (redis-py 8.1.0) is pinned now; the worker framework
(Celery vs ARQ vs Dramatiq) is **deliberately deferred** until the first
concrete asynchronous use case exists, so the choice can be made against
real requirements rather than speculation. Redis/worker remain
infrastructure components, never domain dependencies (AGENTS.md §4).

## Security notes and breaking-change posture

- All pins are exact (`==` / specific image tags). The traceability test
  `tests/test_technology_versions.py` fails if any dependency is left
  unpinned or drifts from this ADR.
- FastAPI is pre-1.0: minor releases may break APIs. Upgrade deliberately,
  reading release notes; patch releases for security fixes should be taken
  promptly.
- redis-py has crossed several majors (5→8); treat major upgrades as
  breaking until proven otherwise.
- SQLAlchemy 2.0.x is a stable series; stay within 2.0 patches. Alembic
  1.20.0 pairs with SQLAlchemy 2.x.
- No open security advisories were known against the selected versions at
  verification time; advisories (GHSA/PyPA/npm) must be checked as part of
  any future version bump.

## Consequences

- `apps/api/pyproject.toml` pins backend runtime dependencies exactly.
- `requirements-dev.txt` pins the repository toolchain (pytest 9.1.1,
  pyyaml 6.0.3) — CI now installs pinned versions.
- `infra/docker-compose.yml` pins `postgres:18.4` and `redis:7.4.11-alpine`.
- `PROJECT_STATE.json` technology_baseline records the verified versions.
- Frontend versions are recorded here and in PROJECT_STATE.json; their
  manifests (package.json) are created with the web scaffold (EPIC-011 and
  TASK-010 contracts tooling).
