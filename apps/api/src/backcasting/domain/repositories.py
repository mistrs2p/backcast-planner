"""Repository interfaces — the domain's persistence ports.

The domain layer defines *what* it needs from persistence; the
infrastructure layer decides *how* (SQLAlchemy + PostgreSQL per ADR-007).
These abstract interfaces keep the dependency direction pointing inward
(AGENTS.md §4): domain code never imports an ORM, and infrastructure
implements these contracts.

Conventions:

- Entities are immutable; repositories store the instance given and return
  the instance stored — identity (UUID) is the key.
- ``get``/lookup methods return ``None`` when nothing matches; absence is
  not an error.
- ``save`` performs insert-or-replace keyed by the entity's id: the domain
  produces new instances on change, so there is no separate update path.
- Implementations raise :class:`RepositoryError` for infrastructure
  failures so callers never see driver-specific exceptions.
- The Future State port exposes a single destination per goal (1:1 in the
  MVP, docs/03-DOMAIN-MODEL.md); enforcing that uniqueness is the
  implementation's job.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Sequence

from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.feedback import Feedback
from backcasting.domain.backcasting_run import BackcastingRun
from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.gap import Gap
from backcasting.domain.goal import Goal
from backcasting.domain.goal_interpretation import GoalInterpretation
from backcasting.domain.milestone import Milestone
from backcasting.domain.outcome import Outcome
from backcasting.domain.outcome_decomposition import OutcomeDecomposition
from backcasting.domain.plan import Plan
from backcasting.domain.plan_explanation import PlanExplanation
from backcasting.domain.strategy_generation import StrategyGeneration
from backcasting.domain.task import Task
from backcasting.domain.task_generation import TaskGeneration
from backcasting.domain.measurement import Measurement
from backcasting.domain.progress import ProgressSnapshot
from backcasting.domain.schedule import Schedule
from backcasting.domain.trigger import Trigger
from backcasting.domain.user import Email, User


class RepositoryError(RuntimeError):
    """Raised by implementations on infrastructure failures."""


class UserRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.user.User`."""

    @abstractmethod
    def save(self, user: User) -> None:
        """Insert or replace the user keyed by ``user_id``."""

    @abstractmethod
    def get(self, user_id: uuid.UUID) -> User | None:
        """Return the user with ``user_id``, or ``None``."""

    @abstractmethod
    def get_by_email(self, email: Email) -> User | None:
        """Return the user with the (normalized) email, or ``None``."""


class GoalRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.goal.Goal`."""

    @abstractmethod
    def save(self, goal: Goal) -> None:
        """Insert or replace the goal keyed by ``goal_id``."""

    @abstractmethod
    def get(self, goal_id: uuid.UUID) -> Goal | None:
        """Return the goal with ``goal_id``, or ``None``."""

    @abstractmethod
    def list_for_user(self, user_id: uuid.UUID) -> Sequence[Goal]:
        """Return the user's goals, oldest first."""


class CurrentStateRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.current_state.CurrentState`."""

    @abstractmethod
    def save(self, state: CurrentState) -> None:
        """Insert or replace the snapshot keyed by ``state_id``."""

    @abstractmethod
    def get(self, state_id: uuid.UUID) -> CurrentState | None:
        """Return the snapshot with ``state_id``, or ``None``."""

    @abstractmethod
    def list_for_goal(self, goal_id: uuid.UUID) -> Sequence[CurrentState]:
        """Return the goal's snapshots, oldest capture first."""

    @abstractmethod
    def latest_for_goal(self, goal_id: uuid.UUID) -> CurrentState | None:
        """Return the most recently captured snapshot, or ``None``."""


class FutureStateRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.future_state.FutureState`."""

    @abstractmethod
    def save(self, state: FutureState) -> None:
        """Insert or replace the destination keyed by ``state_id``."""

    @abstractmethod
    def get(self, state_id: uuid.UUID) -> FutureState | None:
        """Return the destination with ``state_id``, or ``None``."""

    @abstractmethod
    def get_for_goal(self, goal_id: uuid.UUID) -> FutureState | None:
        """Return the goal's destination (1:1 in the MVP), or ``None``."""


class GapRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.gap.Gap`.

    A gap is a recorded calculation (backcasting step 4,
    ``docs/04-BACKCASTING-MODEL.md``), not just a derived value: it
    pins the narrative and dimensions as calculated for one context.
    One per goal in the MVP — redefinition arrives with replanning.
    """

    @abstractmethod
    def save(self, gap: Gap) -> None:
        """Insert or replace the gap keyed by ``gap_id``."""

    @abstractmethod
    def get(self, gap_id: uuid.UUID) -> Gap | None:
        """Return the gap with ``gap_id``, or ``None``."""

    @abstractmethod
    def get_for_goal(self, goal_id: uuid.UUID) -> Gap | None:
        """Return the goal's gap, or ``None``."""


class BackcastingRunRepository(ABC):
    """Persistence port for
    :class:`~backcasting.domain.backcasting_run.BackcastingRun`.

    A goal accumulates runs over time (replanning re-runs the
    engine, docs/03); the latest run is the one the pipeline is
    currently executing.
    """

    @abstractmethod
    def save(self, run: BackcastingRun) -> None:
        """Insert or replace the run keyed by ``run_id``."""

    @abstractmethod
    def get(self, run_id: uuid.UUID) -> BackcastingRun | None:
        """Return the run with ``run_id``, or ``None``."""

    @abstractmethod
    def list_for_goal(self, goal_id: uuid.UUID) -> Sequence[BackcastingRun]:
        """Return the goal's runs, oldest start first."""

    @abstractmethod
    def latest_for_goal(self, goal_id: uuid.UUID) -> BackcastingRun | None:
        """Return the most recently started run, or ``None``."""


class MilestoneRepository(ABC):
    """Persistence port for
    :class:`~backcasting.domain.milestone.Milestone`.

    Milestones belong to a run (generated during it, docs/04 step
    10); listing is therefore per-run, earliest target first — the
    order the path is walked.
    """

    @abstractmethod
    def save(self, milestone: Milestone) -> None:
        """Insert or replace the milestone keyed by ``milestone_id``."""

    @abstractmethod
    def get(self, milestone_id: uuid.UUID) -> Milestone | None:
        """Return the milestone with ``milestone_id``, or ``None``."""

    @abstractmethod
    def list_for_run(self, run_id: uuid.UUID) -> Sequence[Milestone]:
        """Return the run's milestones, earliest target first."""


class PlanRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.plan.Plan`.

    A goal owns plans over time (docs/03 "Goal 1:N Plans"); the MVP
    keeps one per goal — replanning (docs/08) introduces versioned
    successors.
    """

    @abstractmethod
    def save(self, plan: Plan) -> None:
        """Insert or replace the plan keyed by ``plan_id``."""

    @abstractmethod
    def get(self, plan_id: uuid.UUID) -> Plan | None:
        """Return the plan with ``plan_id``, or ``None``."""

    @abstractmethod
    def list_for_goal(self, goal_id: uuid.UUID) -> Sequence[Plan]:
        """Return the goal's plans, oldest first."""


class OutcomeRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.outcome.Outcome`."""

    @abstractmethod
    def save(self, outcome: Outcome) -> None:
        """Insert or replace the outcome keyed by ``outcome_id``."""

    @abstractmethod
    def get(self, outcome_id: uuid.UUID) -> Outcome | None:
        """Return the outcome with ``outcome_id``, or ``None``."""

    @abstractmethod
    def list_for_plan(self, plan_id: uuid.UUID) -> Sequence[Outcome]:
        """Return the plan's outcomes, oldest first."""


class TaskRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.task.Task`."""

    @abstractmethod
    def save(self, task: Task) -> None:
        """Insert or replace the task keyed by ``task_id``."""

    @abstractmethod
    def get(self, task_id: uuid.UUID) -> Task | None:
        """Return the task with ``task_id``, or ``None``."""

    @abstractmethod
    def list_for_plan(self, plan_id: uuid.UUID) -> Sequence[Task]:
        """Return the plan's tasks, oldest first."""


class CalendarRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.calendar.Calendar`.

    A user owns one calendar in the MVP ("User owns calendar",
    docs/03-DOMAIN-MODEL.md); ``get_by_user`` therefore returns the
    user's single calendar or ``None``.
    """

    @abstractmethod
    def save(self, calendar: Calendar) -> None:
        """Insert or replace the calendar keyed by ``calendar_id``."""

    @abstractmethod
    def get(self, calendar_id: uuid.UUID) -> Calendar | None:
        """Return the calendar with ``calendar_id``, or ``None``."""

    @abstractmethod
    def get_by_user(self, user_id: uuid.UUID) -> Calendar | None:
        """Return the user's calendar, or ``None``."""


class CalendarEventRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.calendar_event.CalendarEvent`."""

    @abstractmethod
    def save(self, event: CalendarEvent) -> None:
        """Insert or replace the event keyed by ``event_id``."""

    @abstractmethod
    def list_for_calendar(self, calendar_id: uuid.UUID) -> Sequence[CalendarEvent]:
        """Return the calendar's events, earliest start first."""


class ScheduleRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.schedule.Schedule`.

    "Task 1:N Schedules" (docs/03-DOMAIN-MODEL.md): a task's
    placements — one record per placed part, a split task (TASK-063)
    therefore has several.
    """

    @abstractmethod
    def save(self, schedule: Schedule) -> None:
        """Insert or replace the schedule keyed by ``schedule_id``."""

    @abstractmethod
    def get(self, schedule_id: uuid.UUID) -> Schedule | None:
        """Return the schedule with ``schedule_id``, or ``None``."""

    @abstractmethod
    def list_for_task(self, task_id: uuid.UUID) -> Sequence[Schedule]:
        """Return the task's placements, earliest start first."""


class MeasurementRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.measurement.Measurement`.

    "Measurement: observed data" (docs/02-CONCEPTUAL-MODEL.md): the
    immutable observations that make milestones and outcomes
    measurable. Corrections are new records (new ``measurement_id``),
    never in-place edits.
    """

    @abstractmethod
    def save(self, measurement: Measurement) -> None:
        """Insert or replace the measurement keyed by ``measurement_id``."""

    @abstractmethod
    def get(self, measurement_id: uuid.UUID) -> Measurement | None:
        """Return the measurement with ``measurement_id``, or ``None``."""

    @abstractmethod
    def list_for_subject(self, subject_id: uuid.UUID) -> Sequence[Measurement]:
        """Return the subject's observations, earliest ``measured_at`` first."""


class ProgressSnapshotRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.progress.ProgressSnapshot`.

    Snapshots are the plan-level progress history ("Planned ≠ Actual ≠
    Progress", docs/07-PROGRESS-FEEDBACK.md): an append-only series,
    one reading per taken moment.
    """

    @abstractmethod
    def save(self, snapshot: ProgressSnapshot) -> None:
        """Insert or replace the snapshot keyed by ``snapshot_id``."""

    @abstractmethod
    def get(self, snapshot_id: uuid.UUID) -> ProgressSnapshot | None:
        """Return the snapshot with ``snapshot_id``, or ``None``."""

    @abstractmethod
    def list_for_plan(self, plan_id: uuid.UUID) -> Sequence[ProgressSnapshot]:
        """Return the plan's snapshots, earliest ``taken_at`` first."""


class FeedbackRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.feedback.Feedback`.

    "Feedback: explicit or implicit signals" (docs/02): the
    adaptation layer's other input, recorded verbatim and never
    revised — a correction is a new statement.
    """

    @abstractmethod
    def save(self, feedback: Feedback) -> None:
        """Insert or replace the feedback keyed by ``feedback_id``."""

    @abstractmethod
    def get(self, feedback_id: uuid.UUID) -> Feedback | None:
        """Return the feedback with ``feedback_id``, or ``None``."""

    @abstractmethod
    def list_for_subject(self, subject_id: uuid.UUID) -> Sequence[Feedback]:
        """Return the subject's feedback, earliest ``created_at`` first."""

    @abstractmethod
    def list_all(self) -> Sequence[Feedback]:
        """Return every feedback, earliest ``created_at`` first."""


class TriggerRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.trigger.Trigger`.

    The observed conditions the stability controls (docs/08) judge:
    persistence thresholds, cooldown, and hysteresis all read the
    trigger history. Like every observation, a trigger is an
    immutable fact — it is never revised, only superseded by later
    observations.
    """

    @abstractmethod
    def save(self, trigger: Trigger) -> None:
        """Insert or replace the trigger keyed by ``trigger_id``."""

    @abstractmethod
    def get(self, trigger_id: uuid.UUID) -> Trigger | None:
        """Return the trigger with ``trigger_id``, or ``None``."""

    @abstractmethod
    def list_all(self) -> Sequence[Trigger]:
        """Return every trigger, earliest ``observed_at`` first."""

class GoalInterpretationRepository(ABC):
    """Persistence port for
    :class:`~backcasting.domain.goal_interpretation.GoalInterpretation`.

    The AI layer's proposals, recorded verbatim with provenance and
    never revised (ADR-002) — a re-interpretation is a new record.
    """

    @abstractmethod
    def save(self, interpretation: GoalInterpretation) -> None:
        """Insert or replace the interpretation keyed by
        ``interpretation_id``."""

    @abstractmethod
    def get(self, interpretation_id: uuid.UUID) -> GoalInterpretation | None:
        """Return the interpretation with ``interpretation_id``, or
        ``None``."""

    @abstractmethod
    def list_for_goal(self, goal_id: uuid.UUID) -> Sequence[GoalInterpretation]:
        """Return the goal's interpretations, earliest first."""

class StrategyGenerationRepository(ABC):
    """Persistence port for
    :class:`~backcasting.domain.strategy_generation.StrategyGeneration`.

    The AI layer's strategy generations, recorded verbatim with
    provenance and never revised — regeneration is a new record.
    """

    @abstractmethod
    def save(self, generation: StrategyGeneration) -> None:
        """Insert or replace the generation keyed by
        ``generation_id``."""

    @abstractmethod
    def get(self, generation_id: uuid.UUID) -> StrategyGeneration | None:
        """Return the generation with ``generation_id``, or ``None``."""

    @abstractmethod
    def list_for_goal(self, goal_id: uuid.UUID) -> Sequence[StrategyGeneration]:
        """Return the goal's generations, earliest first."""

class OutcomeDecompositionRepository(ABC):
    """Persistence port for
    :class:`~backcasting.domain.outcome_decomposition.OutcomeDecomposition`.

    The AI layer's outcome decompositions, recorded verbatim with
    provenance and never revised — a re-decomposition is a new
    record.
    """

    @abstractmethod
    def save(self, decomposition: OutcomeDecomposition) -> None:
        """Insert or replace the decomposition keyed by
        ``decomposition_id``."""

    @abstractmethod
    def get(self, decomposition_id: uuid.UUID) -> OutcomeDecomposition | None:
        """Return the decomposition with ``decomposition_id``, or
        ``None``."""

    @abstractmethod
    def list_for_future_state(
        self, future_state_id: uuid.UUID
    ) -> Sequence[OutcomeDecomposition]:
        """Return the future state's decompositions, earliest first."""


class TaskGenerationRepository(ABC):
    """Persistence port for
    :class:`~backcasting.domain.task_generation.TaskGeneration`.

    The AI layer's task generations, recorded verbatim with
    provenance and never revised — a regeneration is a new record.
    """

    @abstractmethod
    def save(self, generation: TaskGeneration) -> None:
        """Insert or replace the generation keyed by
        ``generation_id``."""

    @abstractmethod
    def get(self, generation_id: uuid.UUID) -> TaskGeneration | None:
        """Return the generation with ``generation_id``, or ``None``."""

    @abstractmethod
    def list_for_plan(self, plan_id: uuid.UUID) -> Sequence[TaskGeneration]:
        """Return the plan's task generations, earliest first."""


class PlanExplanationRepository(ABC):
    """Persistence port for
    :class:`~backcasting.domain.plan_explanation.PlanExplanation`.

    The AI layer's plan explanations, recorded verbatim with
    provenance and never revised — a re-explanation is a new record.
    """

    @abstractmethod
    def save(self, explanation: PlanExplanation) -> None:
        """Insert or replace the explanation keyed by
        ``explanation_id``."""

    @abstractmethod
    def get(self, explanation_id: uuid.UUID) -> PlanExplanation | None:
        """Return the explanation with ``explanation_id``, or
        ``None``."""

    @abstractmethod
    def list_for_plan(self, plan_id: uuid.UUID) -> Sequence[PlanExplanation]:
        """Return the plan's explanations, earliest first."""
