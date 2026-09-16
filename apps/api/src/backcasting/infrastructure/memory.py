"""In-memory repository implementations.

Until the production persistence epic delivers SQLAlchemy mappings,
these implementations back the application with process-local storage.
They honor the port contracts exactly (insert-or-replace by id,
``None`` for absence, deterministic ordering) so swapping in the real
implementations later changes wiring, not behavior.
"""

from __future__ import annotations

import threading
import uuid

from backcasting.domain.backcasting_run import BackcastingRun
from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.current_state import CurrentState
from backcasting.domain.execution import Execution
from backcasting.domain.future_state import FutureState
from backcasting.domain.gap import Gap
from backcasting.domain.goal import Goal
from backcasting.domain.milestone import Milestone
from backcasting.domain.outcome import Outcome
from backcasting.domain.plan import Plan
from backcasting.domain.progress import ProgressSnapshot
from backcasting.domain.repositories import (
    BackcastingRunRepository,
    CalendarEventRepository,
    CalendarRepository,
    CurrentStateRepository,
    ExecutionRepository,
    FutureStateRepository,
    GapRepository,
    GoalRepository,
    MilestoneRepository,
    OutcomeRepository,
    PlanRepository,
    ProgressSnapshotRepository,
    RepositoryError,
    TaskRepository,
)
from backcasting.domain.task import Task


class InMemoryGoalRepository(GoalRepository):
    """Goal port backed by a dict, safe for concurrent requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Goal] = {}
        self._lock = threading.Lock()

    def save(self, goal: Goal) -> None:
        with self._lock:
            self._by_id[goal.goal_id] = goal

    def get(self, goal_id: uuid.UUID) -> Goal | None:
        with self._lock:
            return self._by_id.get(goal_id)

    def list_for_user(self, user_id: uuid.UUID):
        with self._lock:
            goals = [g for g in self._by_id.values() if g.user_id == user_id]
        return tuple(sorted(goals, key=lambda g: (g.created_at, g.goal_id)))


class InMemoryCurrentStateRepository(CurrentStateRepository):
    """Current-state port backed by a dict, safe for concurrent
    requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, CurrentState] = {}
        self._lock = threading.Lock()

    def save(self, state: CurrentState) -> None:
        with self._lock:
            self._by_id[state.state_id] = state

    def get(self, state_id: uuid.UUID) -> CurrentState | None:
        with self._lock:
            return self._by_id.get(state_id)

    def list_for_goal(self, goal_id: uuid.UUID):
        with self._lock:
            states = [s for s in self._by_id.values() if s.goal_id == goal_id]
        return tuple(sorted(states, key=lambda s: (s.captured_at, s.state_id)))

    def latest_for_goal(self, goal_id: uuid.UUID) -> CurrentState | None:
        snapshots = self.list_for_goal(goal_id)
        return snapshots[-1] if snapshots else None


class InMemoryFutureStateRepository(FutureStateRepository):
    """Future-state port backed by a dict; one destination per goal
    (the MVP's 1:1, enforced here as the port contract states)."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, FutureState] = {}
        self._by_goal: dict[uuid.UUID, FutureState] = {}
        self._lock = threading.Lock()

    def save(self, state: FutureState) -> None:
        with self._lock:
            previous = self._by_goal.get(state.goal_id)
            if previous is not None and previous.state_id != state.state_id:
                raise RepositoryError(
                    "goal already has a future state (one per goal in the MVP)"
                )
            self._by_id[state.state_id] = state
            self._by_goal[state.goal_id] = state

    def get(self, state_id: uuid.UUID) -> FutureState | None:
        with self._lock:
            return self._by_id.get(state_id)

    def get_for_goal(self, goal_id: uuid.UUID) -> FutureState | None:
        with self._lock:
            return self._by_goal.get(goal_id)


class InMemoryGapRepository(GapRepository):
    """Gap port backed by dicts; one recorded gap per goal (MVP)."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Gap] = {}
        self._by_goal: dict[uuid.UUID, Gap] = {}
        self._lock = threading.Lock()

    def save(self, gap: Gap) -> None:
        with self._lock:
            previous = self._by_goal.get(gap.goal_id)
            if previous is not None and previous.gap_id != gap.gap_id:
                raise RepositoryError(
                    "goal already has a recorded gap (one per goal in the MVP)"
                )
            self._by_id[gap.gap_id] = gap
            self._by_goal[gap.goal_id] = gap

    def get(self, gap_id: uuid.UUID) -> Gap | None:
        with self._lock:
            return self._by_id.get(gap_id)

    def get_for_goal(self, goal_id: uuid.UUID) -> Gap | None:
        with self._lock:
            return self._by_goal.get(goal_id)


class InMemoryBackcastingRunRepository(BackcastingRunRepository):
    """Run port backed by a dict, safe for concurrent requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, BackcastingRun] = {}
        self._lock = threading.Lock()

    def save(self, run: BackcastingRun) -> None:
        with self._lock:
            self._by_id[run.run_id] = run

    def get(self, run_id: uuid.UUID) -> BackcastingRun | None:
        with self._lock:
            return self._by_id.get(run_id)

    def list_for_goal(self, goal_id: uuid.UUID):
        with self._lock:
            runs = [r for r in self._by_id.values() if r.goal_id == goal_id]
        return tuple(sorted(runs, key=lambda r: (r.started_at, r.run_id)))

    def latest_for_goal(self, goal_id: uuid.UUID) -> BackcastingRun | None:
        runs = self.list_for_goal(goal_id)
        return runs[-1] if runs else None


class InMemoryMilestoneRepository(MilestoneRepository):
    """Milestone port backed by a dict, safe for concurrent
    requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Milestone] = {}
        self._lock = threading.Lock()

    def save(self, milestone: Milestone) -> None:
        with self._lock:
            self._by_id[milestone.milestone_id] = milestone

    def get(self, milestone_id: uuid.UUID) -> Milestone | None:
        with self._lock:
            return self._by_id.get(milestone_id)

    def list_for_run(self, run_id: uuid.UUID):
        with self._lock:
            milestones = [
                m for m in self._by_id.values() if m.run_id == run_id
            ]
        return tuple(
            sorted(milestones, key=lambda m: (m.target_date, m.milestone_id))
        )


class InMemoryPlanRepository(PlanRepository):
    """Plan port backed by a dict, safe for concurrent requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Plan] = {}
        self._lock = threading.Lock()

    def save(self, plan: Plan) -> None:
        with self._lock:
            self._by_id[plan.plan_id] = plan

    def get(self, plan_id: uuid.UUID) -> Plan | None:
        with self._lock:
            return self._by_id.get(plan_id)

    def list_for_goal(self, goal_id: uuid.UUID):
        with self._lock:
            plans = [p for p in self._by_id.values() if p.goal_id == goal_id]
        return tuple(sorted(plans, key=lambda p: (p.created_at, p.plan_id)))


class InMemoryOutcomeRepository(OutcomeRepository):
    """Outcome port backed by a dict, safe for concurrent requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Outcome] = {}
        self._lock = threading.Lock()

    def save(self, outcome: Outcome) -> None:
        with self._lock:
            self._by_id[outcome.outcome_id] = outcome

    def get(self, outcome_id: uuid.UUID) -> Outcome | None:
        with self._lock:
            return self._by_id.get(outcome_id)

    def list_for_plan(self, plan_id: uuid.UUID):
        with self._lock:
            outcomes = [
                o for o in self._by_id.values() if o.plan_id == plan_id
            ]
        return tuple(
            sorted(outcomes, key=lambda o: (o.created_at, o.outcome_id))
        )


class InMemoryTaskRepository(TaskRepository):
    """Task port backed by a dict, safe for concurrent requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Task] = {}
        self._lock = threading.Lock()

    def save(self, task: Task) -> None:
        with self._lock:
            self._by_id[task.task_id] = task

    def get(self, task_id: uuid.UUID) -> Task | None:
        with self._lock:
            return self._by_id.get(task_id)

    def list_for_plan(self, plan_id: uuid.UUID):
        with self._lock:
            tasks = [t for t in self._by_id.values() if t.plan_id == plan_id]
        return tuple(sorted(tasks, key=lambda t: (t.created_at, t.task_id)))


class InMemoryExecutionRepository(ExecutionRepository):
    """Execution port backed by a dict, safe for concurrent requests.

    Append-only history: ``save`` only inserts (a revision of a
    sitting is another sitting, docs/07)."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Execution] = {}
        self._lock = threading.Lock()

    def save(self, execution: Execution) -> None:
        with self._lock:
            self._by_id[execution.execution_id] = execution

    def get(self, execution_id: uuid.UUID) -> Execution | None:
        with self._lock:
            return self._by_id.get(execution_id)

    def list_for_task(self, task_id: uuid.UUID):
        with self._lock:
            sittings = [e for e in self._by_id.values() if e.task_id == task_id]
        return tuple(sorted(sittings, key=lambda e: (e.start, e.execution_id)))


class InMemoryProgressSnapshotRepository(ProgressSnapshotRepository):
    """Progress-snapshot port backed by a dict, safe for concurrent
    requests. Append-only history, earliest ``taken_at`` first."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, ProgressSnapshot] = {}
        self._lock = threading.Lock()

    def save(self, snapshot: ProgressSnapshot) -> None:
        with self._lock:
            self._by_id[snapshot.snapshot_id] = snapshot

    def get(self, snapshot_id: uuid.UUID) -> ProgressSnapshot | None:
        with self._lock:
            return self._by_id.get(snapshot_id)

    def list_for_plan(self, plan_id: uuid.UUID):
        with self._lock:
            snapshots = [
                s for s in self._by_id.values() if s.plan_id == plan_id
            ]
        return tuple(sorted(snapshots, key=lambda s: (s.taken_at, s.snapshot_id)))


class InMemoryCalendarRepository(CalendarRepository):
    """Calendar port backed by dicts, safe for concurrent requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Calendar] = {}
        self._by_user: dict[uuid.UUID, Calendar] = {}
        self._lock = threading.Lock()

    def save(self, calendar: Calendar) -> None:
        with self._lock:
            previous = self._by_id.get(calendar.calendar_id)
            if previous is not None and previous.user_id != calendar.user_id:
                raise RepositoryError("calendar id already belongs to another user")
            self._by_id[calendar.calendar_id] = calendar
            self._by_user[calendar.user_id] = calendar

    def get(self, calendar_id: uuid.UUID) -> Calendar | None:
        with self._lock:
            return self._by_id.get(calendar_id)

    def get_by_user(self, user_id: uuid.UUID) -> Calendar | None:
        with self._lock:
            return self._by_user.get(user_id)


class InMemoryCalendarEventRepository(CalendarEventRepository):
    """Calendar-event port backed by a dict, safe for concurrent requests."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, CalendarEvent] = {}
        self._lock = threading.Lock()

    def save(self, event: CalendarEvent) -> None:
        with self._lock:
            self._by_id[event.event_id] = event

    def list_for_calendar(self, calendar_id: uuid.UUID) -> tuple[CalendarEvent, ...]:
        with self._lock:
            events = [e for e in self._by_id.values() if e.calendar_id == calendar_id]
        return tuple(sorted(events, key=lambda e: (e.start, e.event_id)))
