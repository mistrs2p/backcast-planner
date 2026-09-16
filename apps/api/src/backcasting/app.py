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
from backcasting.api.backcast import router as backcast_router
from backcasting.api.calendars import router as calendars_router
from backcasting.api.goals import router as goals_router
from backcasting.api.milestones import router as milestones_router
from backcasting.api.plans import router as plans_router
from backcasting.application.backcast import BackcastService
from backcasting.application.calendars import CalendarService
from backcasting.application.goals import GoalService
from backcasting.application.milestones import MilestoneService
from backcasting.application.plans import PlanService
from backcasting.domain.repositories import (
    BackcastingRunRepository,
    CalendarEventRepository,
    CalendarRepository,
    CurrentStateRepository,
    FutureStateRepository,
    GapRepository,
    GoalRepository,
    MilestoneRepository,
    OutcomeRepository,
    PlanRepository,
    TaskRepository,
)
from backcasting.infrastructure.memory import (
    InMemoryBackcastingRunRepository,
    InMemoryCalendarEventRepository,
    InMemoryCalendarRepository,
    InMemoryCurrentStateRepository,
    InMemoryFutureStateRepository,
    InMemoryGapRepository,
    InMemoryGoalRepository,
    InMemoryMilestoneRepository,
    InMemoryOutcomeRepository,
    InMemoryPlanRepository,
    InMemoryTaskRepository,
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
    current_state_repository: CurrentStateRepository | None = None,
    future_state_repository: FutureStateRepository | None = None,
    gap_repository: GapRepository | None = None,
    run_repository: BackcastingRunRepository | None = None,
    milestone_repository: MilestoneRepository | None = None,
    plan_repository: PlanRepository | None = None,
    outcome_repository: OutcomeRepository | None = None,
    task_repository: TaskRepository | None = None,
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
    goals = goal_repository or InMemoryGoalRepository()
    runs = run_repository or InMemoryBackcastingRunRepository()
    app.state.goal_service = GoalService(goals)
    app.state.backcast_service = BackcastService(
        goals,
        current_state_repository or InMemoryCurrentStateRepository(),
        future_state_repository or InMemoryFutureStateRepository(),
        gap_repository or InMemoryGapRepository(),
        runs,
    )
    milestones = milestone_repository or InMemoryMilestoneRepository()
    app.state.milestone_service = MilestoneService(goals, runs, milestones)
    app.state.plan_service = PlanService(
        goals,
        runs,
        plan_repository or InMemoryPlanRepository(),
        outcome_repository or InMemoryOutcomeRepository(),
        task_repository or InMemoryTaskRepository(),
        milestones,
    )
    app.include_router(calendars_router)
    app.include_router(goals_router)
    app.include_router(backcast_router)
    app.include_router(milestones_router)
    app.include_router(plans_router)

    @app.get("/health", tags=["system"], operation_id="getHealth")
    def health() -> dict[str, str]:
        """Liveness signal for the service."""
        return {"status": "ok"}

    return app
