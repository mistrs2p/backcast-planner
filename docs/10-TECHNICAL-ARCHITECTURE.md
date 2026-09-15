# Technical Architecture

## Baseline
Frontend: Next.js + TypeScript + Tailwind CSS.
Backend: FastAPI + Python.
Database: PostgreSQL.
ORM: SQLAlchemy 2.x.
Migrations: Alembic.
Async: Redis + worker when required.

## Architecture
Modular monolith with Presentation → Application → Domain → Infrastructure.

## Rules
Domain is framework/vendor independent.
API exposes use cases and generated contracts.
Persisted instants use UTC; user timezone is used for interpretation/display.
IDs use UUID or ULID.

## Deployment
Docker-first local development; production adds CI/CD, observability, backups, rollback and smoke tests.
