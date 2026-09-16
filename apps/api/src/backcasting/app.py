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
from backcasting.api.calendars import router as calendars_router
from backcasting.api.goals import router as goals_router
from backcasting.application.calendars import CalendarService
from backcasting.application.goals import GoalService
from backcasting.domain.repositories import (
    CalendarEventRepository,
    CalendarRepository,
    GoalRepository,
)
from backcasting.infrastructure.memory import (
    InMemoryCalendarEventRepository,
    InMemoryCalendarRepository,
    InMemoryGoalRepository,
)

API_TITLE = "Backcasting Planner API"
API_DESCRIPTION = (
    "Adaptive planning system: backcast from a desired future state, plan, "
    "schedule against real calendar and capacity constraints, measure "
    "execution, and replan when reality diverges."
)


def create_app(
    *,
    calendar_repository: CalendarRepository | None = None,
    event_repository: CalendarEventRepository | None = None,
    goal_repository: GoalRepository | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Repositories default to in-memory implementations; production wiring
    (SQLAlchemy + PostgreSQL per ADR-007) injects its own. The use cases
    are composed in ``backcasting.application`` and exposed by the
    routers in ``backcasting.api``.
    """
    app = FastAPI(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=__version__,
    )
    app.state.calendar_service = CalendarService(
        calendar_repository or InMemoryCalendarRepository(),
        event_repository or InMemoryCalendarEventRepository(),
    )
    app.state.goal_service = GoalService(
        goal_repository or InMemoryGoalRepository()
    )
    app.include_router(calendars_router)
    app.include_router(goals_router)

    @app.get("/health", tags=["system"], operation_id="getHealth")
    def health() -> dict[str, str]:
        """Liveness signal for the service."""
        return {"status": "ok"}

    return app
