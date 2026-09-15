# packages/contracts — Shared Contracts

Shared API contracts and schemas consumed by the backend (`apps/api`) and the
frontend (`apps/web`).

Per `docs/10-TECHNICAL-ARCHITECTURE.md`, the API exposes use cases and
generated contracts. The mechanism (established by TASK-010, see
`docs/adr/ADR-008-openapi-contracts.md`):

- The FastAPI application (`backcasting.app.create_app`) is the single source
  of truth; its OpenAPI schema is the API contract.
- `scripts/generate_contracts.py` regenerates `openapi.json` here;
  `--check` fails on drift between the committed artifact and the
  application, and CI enforces it.
- Route changes must regenerate the contract in the same commit.
- Frontend typed clients will be generated from this artifact when the web
  app is scaffolded.
