"""Context builder — operation-specific context for the LLM port.

docs/09-AI-ARCHITECTURE.md's context strategy: "Operation-specific
ContextBuilder; do not resend full history/repository state
unnecessarily." This module is that builder. Each of docs/09's six
AI operations gets a composer whose signature takes *exactly* the
records that operation needs — goal interpretation sees the goal and
the current state, nothing else — so the necessity rule is
structural, not a convention a caller could forget: there is no way
to hand the builder "everything" and let it sort the relevance out.

The mechanical parts:

- Every operation has one fixed system instruction (its slice of
  :data:`OPERATION_INSTRUCTIONS`), each ending where ADR-002 begins:
  the LLM proposes, the domain validates. An unknown operation is
  rejected — a generic fallback instruction would silently produce
  unspecific context, the exact failure the strategy forbids.
- Context rides as named sections (heading + body), rendered into a
  single user message in the order given. Sections are the caller's
  vocabulary; the per-operation record renderers below are the
  curated ones, selecting fields rather than dumping records: ids,
  timestamps, and bookkeeping fields stay out unless an operation
  demonstrably needs them.
- The result is a complete :class:`~backcasting.domain.llm_provider.LLMRequest`
  — the operations (TASK-095 onward) hand it straight to an
  :class:`~backcasting.domain.llm_provider.LLMProvider`.

This module lives in the application layer, not the domain: it is
orchestration for the AI use cases, holds no domain rules of its
own, and imports nothing the domain forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import Goal
from backcasting.domain.llm_provider import LLMRequest, Message, MessageRole
from backcasting.domain.outcome import Outcome
from backcasting.domain.plan import Plan
from backcasting.domain.progress import ProgressSnapshot
from backcasting.domain.task import Task

PROPOSAL_REMINDER = "You propose; the system validates and enforces."

OPERATION_INSTRUCTIONS: dict[str, str] = {
    "goal-interpretation": (
        "Interpret the user's goal against their current state. Propose a "
        "clear reading of the goal: its essence, what success looks like, "
        "and any ambiguity worth clarifying. " + PROPOSAL_REMINDER
    ),
    "clarification": (
        "The goal is ambiguous. Propose the single most useful question to "
        "ask the user next, and nothing else. " + PROPOSAL_REMINDER
    ),
    "strategy-generation": (
        "Given the goal, the current state, and the desired future state, "
        "propose candidate strategies for getting from here to there. "
        + PROPOSAL_REMINDER
    ),
    "outcome-decomposition": (
        "Given the desired future state, propose the outcomes that must "
        "exist for it to hold. " + PROPOSAL_REMINDER
    ),
    "task-generation": (
        "Given the outcomes, propose the concrete tasks that produce "
        "them, each small enough to schedule. " + PROPOSAL_REMINDER
    ),
    "explanation": (
        "Given the plan and its progress, explain in plain language where "
        "the plan stands and what comes next. " + PROPOSAL_REMINDER
    ),
}


class ContextBuilderError(ValueError):
    """Raised when a context-building invariant is violated."""


@dataclass(frozen=True)
class ContextSection:
    """One named piece of context, rendered under its heading."""

    heading: str
    body: str

    def __post_init__(self) -> None:
        if not isinstance(self.heading, str) or not self.heading.strip():
            raise ContextBuilderError("heading must be a non-empty string")
        if not isinstance(self.body, str) or not self.body.strip():
            raise ContextBuilderError("body must be a non-empty string")

    def render(self) -> str:
        return f"## {self.heading}\n{self.body}"


def _hours(amount: timedelta) -> str:
    """Render a workload as plain hours, without trailing noise."""
    return f"{amount.total_seconds() / 3600:g}"


def build_context(
    operation: str,
    sections: tuple[ContextSection, ...],
    *,
    model: str | None = None,
    max_output_tokens: int | None = None,
    temperature: float | None = None,
) -> LLMRequest:
    """Assemble one operation's context into a complete request.

    ``operation`` must be one of docs/09's six (see
    :data:`OPERATION_INSTRUCTIONS`) and ``sections`` non-empty: an
    operation with no context has nothing to reason about, and a
    request built anyway would be the unspecific-context failure the
    strategy forbids.
    """
    if operation not in OPERATION_INSTRUCTIONS:
        known = ", ".join(sorted(OPERATION_INSTRUCTIONS))
        raise ContextBuilderError(
            f"unknown operation {operation!r}; known operations: {known}"
        )
    if not isinstance(sections, tuple):
        raise ContextBuilderError("sections must be a tuple of ContextSection")
    if not sections:
        raise ContextBuilderError("sections must not be empty")
    for section in sections:
        if not isinstance(section, ContextSection):
            raise ContextBuilderError("sections must be ContextSection instances")

    return LLMRequest(
        operation=operation,
        messages=(
            Message(MessageRole.SYSTEM, OPERATION_INSTRUCTIONS[operation]),
            Message(
                MessageRole.USER,
                "\n\n".join(section.render() for section in sections),
            ),
        ),
        model=model,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
    )


# --- Record renderers: fields in, sections out; ids and bookkeeping
# --- stay out unless an operation demonstrably needs them.


def goal_section(goal: Goal) -> ContextSection:
    """The goal as interpretation needs it: title and description."""
    if not isinstance(goal, Goal):
        raise ContextBuilderError("goal must be a Goal")
    body = goal.title if not goal.description else (
        f"{goal.title}\n\n{goal.description}"
    )
    return ContextSection("Goal", body)


def current_state_section(state: CurrentState) -> ContextSection:
    """The current state as the starting point of every backcast."""
    if not isinstance(state, CurrentState):
        raise ContextBuilderError("state must be a CurrentState")
    return ContextSection("Current state", state.narrative)


def future_state_section(state: FutureState) -> ContextSection:
    """The destination: what must hold, and by when."""
    if not isinstance(state, FutureState):
        raise ContextBuilderError("state must be a FutureState")
    return ContextSection(
        "Future state",
        f"{state.description}\n\nTarget date: {state.target_date.date().isoformat()}",
    )


def outcomes_section(outcomes: tuple[Outcome, ...]) -> ContextSection:
    """The outcomes a task set must produce, as a list."""
    if not isinstance(outcomes, tuple):
        raise ContextBuilderError("outcomes must be a tuple of Outcome")
    if not outcomes:
        raise ContextBuilderError("outcomes must not be empty")
    for outcome in outcomes:
        if not isinstance(outcome, Outcome):
            raise ContextBuilderError("outcomes must be Outcome instances")
    lines = [
        f"- {o.title}" if not o.description else f"- {o.title}: {o.description}"
        for o in outcomes
    ]
    return ContextSection("Outcomes", "\n".join(lines))


def plan_section(plan: Plan, tasks: tuple[Task, ...]) -> ContextSection:
    """The plan as explanation needs it: what it holds, and the tasks
    that make it up. Task ids stay out; the reader is a language
    model, not a join."""
    if not isinstance(plan, Plan):
        raise ContextBuilderError("plan must be a Plan")
    if not isinstance(tasks, tuple):
        raise ContextBuilderError("tasks must be a tuple of Task")
    for task in tasks:
        if not isinstance(task, Task):
            raise ContextBuilderError("tasks must be Task instances")
    lines = [f"Total workload: {_hours(plan.workload)} hours"]
    if plan.title:
        lines.insert(0, plan.title)
    for index, task in enumerate(tasks, start=1):
        duration = (
            f"{_hours(task.duration)} hours"
            if task.duration is not None
            else "no estimate yet"
        )
        lines.append(f"{index}. {task.title} ({duration})")
    return ContextSection("Plan", "\n".join(lines))


def progress_section(snapshot: ProgressSnapshot) -> ContextSection:
    """The plan's progress as plain numbers."""
    if not isinstance(snapshot, ProgressSnapshot):
        raise ContextBuilderError("snapshot must be a ProgressSnapshot")
    return ContextSection(
        "Progress",
        "\n".join(
            (
                f"Planned: {_hours(snapshot.planned)} hours",
                f"Actually worked: {_hours(snapshot.actual)} hours",
                f"Remaining: {_hours(snapshot.remaining)} hours",
                f"Tasks completed: {snapshot.completed_task_count} of "
                f"{snapshot.task_count}",
            )
        ),
    )


# --- The per-operation composers: each takes exactly the records its
# --- operation needs — the "no unnecessary resend" rule, structural.


def build_goal_interpretation_context(
    goal: Goal, state: CurrentState
) -> LLMRequest:
    return build_context(
        "goal-interpretation",
        (goal_section(goal), current_state_section(state)),
    )


def build_clarification_context(goal: Goal, state: CurrentState) -> LLMRequest:
    return build_context(
        "clarification",
        (goal_section(goal), current_state_section(state)),
    )


def build_strategy_context(
    goal: Goal, state: CurrentState, future: FutureState
) -> LLMRequest:
    return build_context(
        "strategy-generation",
        (goal_section(goal), current_state_section(state), future_state_section(future)),
    )


def build_outcome_decomposition_context(future: FutureState) -> LLMRequest:
    return build_context("outcome-decomposition", (future_state_section(future),))


def build_task_generation_context(
    outcomes: tuple[Outcome, ...],
) -> LLMRequest:
    return build_context("task-generation", (outcomes_section(outcomes),))


def build_explanation_context(
    plan: Plan, tasks: tuple[Task, ...], snapshot: ProgressSnapshot
) -> LLMRequest:
    return build_context(
        "explanation",
        (plan_section(plan, tasks), progress_section(snapshot)),
    )
