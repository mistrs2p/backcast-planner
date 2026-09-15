# infra — Infrastructure

Infrastructure definitions for the Backcasting Goal & Adaptive Planning
System.

Baseline: Docker-first local development with PostgreSQL, Redis, and a worker;
production adds CI/CD, observability, backups, rollback, and smoke tests
(`docs/10-TECHNICAL-ARCHITECTURE.md`, `docs/14-DEPLOYMENT.md`).

Docker Compose baseline (TASK-007): `infra/docker-compose.yml` provides
PostgreSQL 18 and Redis with health checks and a persistent postgres volume.

```sh
docker compose -f infra/docker-compose.yml up -d --wait
```

Credentials come from environment variables with local defaults
(`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`,
`REDIS_PORT`). Application services (api, web, worker) are added together
with their Dockerfiles when the applications are scaffolded.
