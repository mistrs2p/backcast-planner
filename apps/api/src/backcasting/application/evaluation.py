"""The AI evaluation dataset and its runner (TASK-102).

An AI layer that proposes must be evaluable against something
stable: docs/09's operations change behavior as prompts, models,
and schemas evolve, and a regression in the pipeline — context
building, schema validation, deterministic acceptance — should be
caught by replaying known cases, not by discovering it in
production. The dataset (``apps/api/evals/ai_operations.json``)
holds one golden response per case; the runner replays each case
through the full deterministic arc — build the context, feed the
golden response through a scripted provider, parse it under the
operation's schema, and pass the parsed proposals through the
deterministic acceptors — and reports one verdict per case.

Everything is reproducible: ids derive from the case id (UUID v5)
and timestamps from a fixed epoch, so a case that passes today and
fails tomorrow means the *code* changed, not the dice. The dataset
covers the three operations whose proposals have schemas (goal
interpretation, clarification, and explanation have no
deterministic target to evaluate against — their records end the
arc, and replaying them would test nothing but json.loads).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from backcasting.application.validated_generation import (
    generate_validated_outcomes,
    generate_validated_strategies,
    generate_validated_tasks,
)
from backcasting.domain.backcasting_run import start_run
from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.gap import calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
)
from backcasting.domain.outcome import define_outcome
from backcasting.domain.plan import create_plan
from backcasting.domain.strategy import accept_proposed_strategies
from backcasting.domain.task import accept_proposed_tasks

EVALUABLE_OPERATIONS = frozenset(
    {"strategy-generation", "outcome-decomposition", "task-generation"}
)
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
NAMESPACE = uuid.UUID("2f0ac1a4-0e6b-4d1a-9a63-8c1f4a7e2b91")

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[3] / "evals" / "ai_operations.json"
)


class EvaluationDatasetError(ValueError):
    """Raised when the evaluation dataset is malformed."""


@dataclass(frozen=True)
class EvaluationCase:
    """One replayable case: the backcast anchors, the operation's
    extras, and the golden response."""

    case_id: str
    operation: str
    goal_title: str
    goal_description: str
    current_narrative: str
    future_description: str
    future_target_date: date
    gap_narrative: str
    plan_workload_hours: float
    outcome_titles: tuple[str, ...]
    expected_response: str

    def __post_init__(self) -> None:
        for name in ("case_id", "goal_title", "current_narrative",
                     "future_description"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise EvaluationDatasetError(
                    f"{name} must be a non-empty string"
                )
        if self.operation not in EVALUABLE_OPERATIONS:
            raise EvaluationDatasetError(
                f"case {self.case_id!r}: operation {self.operation!r} is "
                "not evaluable — the evaluable operations are: "
                f"{', '.join(sorted(EVALUABLE_OPERATIONS))}"
            )
        if self.operation == "strategy-generation" and not self.gap_narrative.strip():
            raise EvaluationDatasetError(
                f"case {self.case_id!r}: strategy cases need a "
                "gap_narrative"
            )
        if self.operation == "task-generation":
            if not self.outcome_titles:
                raise EvaluationDatasetError(
                    f"case {self.case_id!r}: task cases need outcome_titles"
                )
            for title in self.outcome_titles:
                if not isinstance(title, str) or not title.strip():
                    raise EvaluationDatasetError(
                        f"case {self.case_id!r}: outcome titles must be "
                        "non-empty strings"
                    )
        if not isinstance(self.expected_response, str) or not self.expected_response.strip():
            raise EvaluationDatasetError(
                f"case {self.case_id!r}: expected_response must be a "
                "non-empty string"
            )


@dataclass(frozen=True)
class CaseResult:
    """One case's verdict: passed, or the detail of why not."""

    case_id: str
    operation: str
    passed: bool
    detail: str = ""


def _mapping(raw: object, key: str, case_id: str) -> dict:
    if not isinstance(raw, dict):
        raise EvaluationDatasetError(
            f"case {case_id!r}: {key} must be an object"
        )
    return raw


def _string(holder: dict, key: str, case_id: str, default: str = "") -> str:
    value = holder.get(key, default)
    if not isinstance(value, str):
        raise EvaluationDatasetError(
            f"case {case_id!r}: {key} must be a string"
        )
    return value


def load_dataset(path: Path | None = None) -> tuple[EvaluationCase, ...]:
    """Load and validate the dataset at ``path`` (default: the
    repository's)."""
    dataset_path = path if path is not None else DEFAULT_DATASET_PATH
    try:
        raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise EvaluationDatasetError(
            f"cannot read evaluation dataset {dataset_path}: {error}"
        ) from error
    if not isinstance(raw, list) or not raw:
        raise EvaluationDatasetError(
            "the evaluation dataset must be a non-empty JSON array"
        )
    seen: set[str] = set()
    cases: list[EvaluationCase] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise EvaluationDatasetError("each dataset entry must be an object")
        case_id = entry.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise EvaluationDatasetError("each entry needs a non-empty case_id")
        if case_id in seen:
            raise EvaluationDatasetError(
                f"duplicate case_id in dataset: {case_id!r}"
            )
        seen.add(case_id)
        operation = _string(entry, "operation", case_id)
        goal = _mapping(entry.get("goal"), "goal", case_id)
        state = _mapping(entry.get("current_state"), "current_state", case_id)
        future = _mapping(entry.get("future_state"), "future_state", case_id)
        target_raw = _string(future, "target_date", case_id)
        try:
            target_date = date.fromisoformat(target_raw)
        except ValueError as error:
            raise EvaluationDatasetError(
                f"case {case_id!r}: target_date {target_raw!r} is not a "
                "YYYY-MM-DD date"
            ) from error
        workload = entry.get("plan_workload_hours", 0)
        if isinstance(workload, bool) or not isinstance(workload, (int, float)):
            raise EvaluationDatasetError(
                f"case {case_id!r}: plan_workload_hours must be a number"
            )
        outcome_titles = entry.get("outcome_titles", [])
        if not isinstance(outcome_titles, list):
            raise EvaluationDatasetError(
                f"case {case_id!r}: outcome_titles must be an array"
            )
        cases.append(
            EvaluationCase(
                case_id=case_id,
                operation=operation,
                goal_title=_string(goal, "title", case_id),
                goal_description=_string(goal, "description", case_id),
                current_narrative=_string(state, "narrative", case_id),
                future_description=_string(future, "description", case_id),
                future_target_date=target_date,
                gap_narrative=_string(entry, "gap_narrative", case_id),
                plan_workload_hours=float(workload),
                outcome_titles=tuple(outcome_titles),
                expected_response=_string(entry, "expected_response", case_id),
            )
        )
    return tuple(cases)


class _ScriptedProvider(LLMProvider):
    """Replays the case's golden response, exactly once."""

    def __init__(self, content: str):
        self._content = content

    @property
    def name(self) -> str:
        return "scripted"

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content=self._content, model="scripted-golden")


def _build_records(case: EvaluationCase):
    seed = uuid.uuid5(NAMESPACE, case.case_id)
    goal = create_goal(
        seed,
        case.goal_title,
        description=case.goal_description,
        goal_id=uuid.uuid5(NAMESPACE, case.case_id + ":goal"),
        created_at=EPOCH,
    )
    state = CurrentState(
        state_id=uuid.uuid5(NAMESPACE, case.case_id + ":current"),
        goal_id=goal.goal_id,
        narrative=case.current_narrative,
        captured_at=EPOCH,
    )
    future = FutureState(
        state_id=uuid.uuid5(NAMESPACE, case.case_id + ":future"),
        goal_id=goal.goal_id,
        description=case.future_description,
        target_date=datetime(
            case.future_target_date.year,
            case.future_target_date.month,
            case.future_target_date.day,
            tzinfo=timezone.utc,
        ),
        created_at=EPOCH,
        updated_at=EPOCH,
    )
    return goal, state, future


def run_case(case: EvaluationCase) -> CaseResult:
    """Replay one case through the full deterministic arc."""
    try:
        goal, state, future = _build_records(case)
        provider = _ScriptedProvider(case.expected_response)
        if case.operation == "strategy-generation":
            gap = calculate_gap(
                goal,
                state,
                future,
                narrative=case.gap_narrative,
                calculated_at=EPOCH,
            )
            run = start_run(goal, state, future, gap, started_at=EPOCH)
            _, proposals = generate_validated_strategies(
                goal, state, future, provider
            )
            accept_proposed_strategies(run, proposals, at=EPOCH)
        elif case.operation == "outcome-decomposition":
            _, titles = generate_validated_outcomes(future, provider)
            if not titles:
                raise ValueError("no outcome titles parsed")
            plan = create_plan(
                goal, timedelta(hours=case.plan_workload_hours), created_at=EPOCH
            )
            for title in titles:
                define_outcome(plan, title, created_at=EPOCH)
        else:
            plan = create_plan(
                goal, timedelta(hours=case.plan_workload_hours), created_at=EPOCH
            )
            outcomes = tuple(
                define_outcome(plan, title, created_at=EPOCH)
                for title in case.outcome_titles
            )
            _, proposals = generate_validated_tasks(outcomes, provider)
            accept_proposed_tasks(plan, outcomes, proposals, at=EPOCH)
    except Exception as error:  # noqa: BLE001 — one verdict per case
        return CaseResult(
            case_id=case.case_id,
            operation=case.operation,
            passed=False,
            detail=f"{type(error).__name__}: {error}",
        )
    return CaseResult(case_id=case.case_id, operation=case.operation, passed=True)


def run_dataset(
    cases: tuple[EvaluationCase, ...],
) -> tuple[CaseResult, ...]:
    """Replay every case, one verdict per case."""
    if not isinstance(cases, tuple):
        raise EvaluationDatasetError("cases must be a tuple of EvaluationCase")
    return tuple(run_case(case) for case in cases)
