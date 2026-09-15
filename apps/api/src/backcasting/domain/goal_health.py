"""Goal health — the roll-up of the progress signals.

docs/07-PROGRESS-FEEDBACK.md closes its signal list with
"completion rate, on-time rate"; goal health is where the signals
meet: one categorical reading — on track, at risk, off track —
derived mechanically from what the other modules state.

:func:`on_time_rate` supplies the missing signal: of the tasks that
finished, the fraction that finished by their deadline. A task
without a deadline has no timeliness to measure and is not counted;
a task without an estimate has no completion to judge and makes the
rate unknown (the workload stance of
:func:`~backcasting.domain.task_estimation.estimate_workload`).

:func:`assess_goal_health` then rolls up, with every rule explicit
and every trigger leaving a machine-readable reason slug:

- a complete plan is on track, full stop — the goal of the plan
  is achieved;
- a projected completion past the deadline is off track: at the
  observed pace the plan will arrive late;
- any unfavorable variance, a decelerating trend, or completed
  tasks that finished late put the goal at risk — evidence, not
  verdicts;
- nothing triggered means on track with no adverse signals.

The ordering (off track > at risk > on track) is fixed; what to
*do* about a poor reading is docs/08's adaptation ladder, upstream
of this statement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from backcasting.domain.execution import Execution
from backcasting.domain.progress import ProgressSnapshot
from backcasting.domain.task import Task
from backcasting.domain.timezone import require_utc
from backcasting.domain.trend import Trend
from backcasting.domain.variance import Variance


class GoalHealthError(ValueError):
    """Raised when a goal-health invariant is violated."""


class GoalHealthStatus(str, Enum):
    """The categorical roll-up of the progress signals."""

    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OFF_TRACK = "off_track"


@dataclass(frozen=True)
class GoalHealth:
    """One roll-up reading, with the reasons that produced it."""

    status: GoalHealthStatus
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, GoalHealthStatus):
            raise GoalHealthError("status must be a GoalHealthStatus")
        if not isinstance(self.reasons, tuple):
            raise GoalHealthError("reasons must be a tuple of strings")
        for reason in self.reasons:
            if not isinstance(reason, str) or not reason:
                raise GoalHealthError("reasons must be non-empty strings")
        if self.status is GoalHealthStatus.ON_TRACK and not self.reasons:
            return  # on track by absence of adverse signals
        if not self.reasons:
            raise GoalHealthError("a non-on-track reading must carry reasons")


def on_time_rate(
    tasks: tuple[Task, ...],
    executions: tuple[Execution, ...],
    *,
    at: datetime,
) -> float | None:
    """Of the finished deadline-bearing tasks, the fraction on time.

    ``None`` when no deadline-bearing task has finished — no
    evidence either way. The completion moment is when the task's
    cumulative actual workload first reaches its duration (the end
    of the sitting that crossed the line), so late sittings after
    an on-time finish do not retroactively make it late.
    """
    if not isinstance(tasks, tuple):
        raise GoalHealthError("tasks must be a tuple of Task")
    for task in tasks:
        if not isinstance(task, Task):
            raise GoalHealthError("tasks must be Task instances")
    if not isinstance(executions, tuple):
        raise GoalHealthError("executions must be a tuple of Execution")
    for execution in executions:
        if not isinstance(execution, Execution):
            raise GoalHealthError("executions must be Execution instances")
    require_utc("at", at, error=GoalHealthError)

    completed = on_time = 0
    for task in tasks:
        if task.deadline is None:
            continue
        if task.duration is None:
            raise GoalHealthError(
                f"task {task.task_id} ({task.title!r}) has no estimate"
            )
        sittings = sorted(
            (
                execution
                for execution in executions
                if execution.task_id == task.task_id and execution.end <= at
            ),
            key=lambda execution: execution.end,
        )
        cumulative = timedelta(0)
        completion_moment = None
        for execution in sittings:
            cumulative += execution.duration
            if completion_moment is None and cumulative >= task.duration:
                completion_moment = execution.end
        if completion_moment is not None:
            completed += 1
            if completion_moment <= task.deadline:
                on_time += 1
    if completed == 0:
        return None
    return on_time / completed


def assess_goal_health(
    snapshot: ProgressSnapshot,
    *,
    variances: tuple[Variance, ...] = (),
    trend: Trend | None = None,
    deadline: datetime | None = None,
    projected_completion: datetime | None = None,
    on_time: float | None = None,
) -> GoalHealth:
    """Roll the signals up into one reading with explicit reasons.

    ``snapshot`` states progress; ``variances`` (any kinds),
    ``trend``, ``projected_completion`` vs ``deadline``, and
    ``on_time`` are the adverse-signal inputs — each optional, each
    checked mechanically when present.
    """
    if not isinstance(snapshot, ProgressSnapshot):
        raise GoalHealthError("snapshot must be a ProgressSnapshot")
    if not isinstance(variances, tuple):
        raise GoalHealthError("variances must be a tuple of Variance")
    for variance in variances:
        if not isinstance(variance, Variance):
            raise GoalHealthError("variances must be Variance instances")
    if trend is not None and not isinstance(trend, Trend):
        raise GoalHealthError("trend must be a Trend or None")
    if deadline is not None:
        require_utc("deadline", deadline, error=GoalHealthError)
    if projected_completion is not None:
        require_utc("projected_completion", projected_completion, error=GoalHealthError)
    if on_time is not None:
        if not isinstance(on_time, (int, float)) or isinstance(on_time, bool):
            raise GoalHealthError("on_time must be a number or None")
        if not 0.0 <= on_time <= 1.0:
            raise GoalHealthError("on_time must be within [0, 1]")

    if snapshot.progress >= 1.0:
        return GoalHealth(GoalHealthStatus.ON_TRACK, ("plan-complete",))

    off_track: list[str] = []
    at_risk: list[str] = []

    if (
        projected_completion is not None
        and deadline is not None
        and projected_completion > deadline
    ):
        off_track.append("projected-deadline-miss")
    for variance in variances:
        if not variance.favorable:
            at_risk.append(f"unfavorable-{variance.kind.value}-variance")
    if trend is not None and trend.direction.value == "decelerating":
        at_risk.append("decelerating-trend")
    if on_time is not None and on_time < 1.0:
        at_risk.append("late-completions")

    if off_track:
        return GoalHealth(GoalHealthStatus.OFF_TRACK, tuple(off_track + at_risk))
    if at_risk:
        return GoalHealth(GoalHealthStatus.AT_RISK, tuple(at_risk))
    return GoalHealth(GoalHealthStatus.ON_TRACK, ())
