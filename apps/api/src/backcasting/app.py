"""FastAPI application factory for the backcasting backend.

The application is assembled here (application/presentation layer); domain
logic lives in ``backcasting.domain`` and must stay framework-independent
(AGENTS.md §4). The factory pattern keeps app creation explicit and testable,
and gives the OpenAPI contract generator (``scripts/generate_contracts.py``)
a stable entry point.

The OpenAPI schema produced by this application is the shared contract
between backend and frontend (ADR-008); generated artifacts live in
``packages/contracts``.
"""

from __future__ import annotations

from fastapi import FastAPI

from backcasting import __version__

API_TITLE = "Backcasting Planner API"
API_DESCRIPTION = (
    "Adaptive planning system: backcast from a desired future state, plan, "
    "schedule against real calendar and capacity constraints, measure "
    "execution, and replan when reality diverges."
)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=__version__,
    )

    @app.get("/health", tags=["system"], operation_id="getHealth")
    def health() -> dict[str, str]:
        """Liveness signal for the service."""
        return {"status": "ok"}

    return app
