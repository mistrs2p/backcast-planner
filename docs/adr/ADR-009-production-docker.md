# ADR-009: Production Docker topology

Date: 2026-09-16
Status: Accepted
Task: TASK-117

## Context

docs/10-TECHNICAL-ARCHITECTURE.md requires "Docker-first local
development; production adds CI/CD, observability, backups,
rollback and smoke tests." The system is a modular monolith with two
deployable units: the FastAPI backend (`apps/api`) and the Next.js
frontend (`apps/web`). The browser talks to one origin — the web
app — and Next proxies `/api/*` to the backend (ADR-008), so
`API_ORIGIN` is a server-side deployment knob, never a browser
concern.

## Decision

1. **One image per deployable unit.** Each app gets its own
   multi-stage Dockerfile (`builder` → `runtime`): the build
   toolchain stays in the builder, the runtime ships only the venv
   plus source (API) or the built app plus its modules (web). Both
   containers run as non-root users and carry their own
   `HEALTHCHECK` — the "health check" step of docs/14's pipeline
   travels with the image, not with whoever deploys it.

2. **`API_ORIGIN` is set twice in the web image, deliberately.**
   The build stage receives it as an ARG because Next bakes the
   `/api` rewrite destination into the build output; the runtime
   stage sets it as an ENV because the server-side fetches
   (`lib/server-api`) read the variable again at `next start`.
   This was learned live in TASK-111's smoke test: setting only one
   of the two serves the wrong backend for half the traffic. The
   compose file passes the same value to both, and
   `scripts/check_docker.py` enforces that they agree.

3. **`docker-compose.yml` is the local environment.** Two services
   on one network, `web` gated on `api`'s health check,
   configuration from the environment (`.env`, placeholders in
   `.env.example`), no secrets in the file. No PostgreSQL or Redis
   service is wired yet, and none is pretended: the backend's
   persistence is in-memory until the migration pipeline (TASK-119)
   delivers the SQLAlchemy repositories. A restart starts a clean
   slate — the compose file says so.

4. **Structural invariants are checked statically.**
   `scripts/check_docker.py` pins the multi-stage/non-root/
   healthchecked shape, the `.dockerignore` exclusions, the
   API_ORIGIN build/runtime agreement, and the absence of secret
   keys in compose — the same stance `scripts/check_rules.py` takes
   for the AGENTS.md rules. Building and running the images is
   validated by `docker compose up --build` itself.

## Consequences

- The web image is larger than a standalone-output build would be
  (full `node_modules` ride along). We deliberately did not switch
  `next.config.ts` to `output: "standalone"` here: it changes the
  build's output contract for an optimization, and TASK-117's scope
  is the deployment topology, not image-size tuning. The switch is
  a contained follow-up if image size matters.
- Images are built with `API_ORIGIN` baked in, so one image build
  serves one backend origin. That is acceptable for this topology
  (compose builds per environment); a multi-environment registry
  flow arrives with CI/CD (TASK-118) and can revisit.
- Host port 3000 was occupied on the development machine; compose
  maps `3300:3000` for the web service.
