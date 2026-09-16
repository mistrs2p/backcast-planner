"""Tests for the AI evaluation dataset (TASK-102).

The dataset is a regression net: every golden case must replay
green through the full deterministic arc, and the harness must
reject malformed datasets and report failures honestly.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from backcasting.application.evaluation import (
    DEFAULT_DATASET_PATH,
    EVALUABLE_OPERATIONS,
    EvaluationCase,
    EvaluationDatasetError,
    load_dataset,
    run_case,
    run_dataset,
)


def _case(**overrides) -> EvaluationCase:
    kwargs = dict(
        case_id="case-x",
        operation="outcome-decomposition",
        goal_title="Run a marathon",
        goal_description="Under five hours.",
        current_narrative="A 10 km week.",
        future_description="A marathon finished.",
        future_target_date=date(2026, 10, 11),
        gap_narrative="",
        plan_workload_hours=160,
        outcome_titles=(),
        expected_response='["Aerobic base built"]',
    )
    kwargs.update(overrides)
    return EvaluationCase(**kwargs)


class TestTheDataset:
    def test_every_case_replays_green(self) -> None:
        results = run_dataset(load_dataset())
        failures = [r for r in results if not r.passed]
        assert not failures, "\n".join(
            f"{r.case_id}: {r.detail}" for r in failures
        )

    def test_the_dataset_covers_every_evaluable_operation(self) -> None:
        cases = load_dataset()
        covered = {case.operation for case in cases}
        assert covered == EVALUABLE_OPERATIONS
        assert len(cases) >= 6

    def test_the_dataset_is_valid_json_at_the_default_path(self) -> None:
        raw = json.loads(
            DEFAULT_DATASET_PATH.read_text(encoding="utf-8")
        )
        assert isinstance(raw, list) and len(raw) >= 6


class TestCaseValidation:
    def test_only_evaluable_operations(self) -> None:
        with pytest.raises(EvaluationDatasetError, match="not evaluable"):
            _case(operation="explanation")

    def test_strategy_cases_need_a_gap_narrative(self) -> None:
        with pytest.raises(EvaluationDatasetError, match="gap_narrative"):
            _case(
                operation="strategy-generation", gap_narrative="  "
            )

    def test_task_cases_need_outcome_titles(self) -> None:
        with pytest.raises(EvaluationDatasetError, match="outcome_titles"):
            _case(operation="task-generation", outcome_titles=())

    def test_empty_fields_are_rejected(self) -> None:
        with pytest.raises(EvaluationDatasetError, match="goal_title"):
            _case(goal_title="  ")
        with pytest.raises(EvaluationDatasetError, match="expected_response"):
            _case(expected_response=" ")


class TestLoadDataset:
    def _write(self, tmp_path: Path, payload) -> Path:
        path = tmp_path / "dataset.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _valid_entry(self) -> dict:
        return {
            "case_id": "one",
            "operation": "outcome-decomposition",
            "goal": {"title": "G", "description": ""},
            "current_state": {"narrative": "N"},
            "future_state": {
                "description": "F",
                "target_date": "2026-10-11",
            },
            "plan_workload_hours": 10,
            "expected_response": '["O"]',
        }

    def test_loads_a_valid_dataset(self, tmp_path) -> None:
        cases = load_dataset(self._write(tmp_path, [self._valid_entry()]))
        assert len(cases) == 1
        assert cases[0].case_id == "one"
        assert cases[0].outcome_titles == ()

    def test_duplicate_case_ids_are_rejected(self, tmp_path) -> None:
        with pytest.raises(EvaluationDatasetError, match="duplicate"):
            load_dataset(
                self._write(
                    tmp_path, [self._valid_entry(), self._valid_entry()]
                )
            )

    def test_missing_file_is_rejected(self, tmp_path) -> None:
        with pytest.raises(EvaluationDatasetError, match="cannot read"):
            load_dataset(tmp_path / "nope.json")

    def test_non_array_is_rejected(self, tmp_path) -> None:
        with pytest.raises(EvaluationDatasetError, match="JSON array"):
            load_dataset(self._write(tmp_path, {"case_id": "one"}))

    def test_bad_target_date_is_rejected(self, tmp_path) -> None:
        entry = self._valid_entry()
        entry["future_state"]["target_date"] = "October"
        with pytest.raises(EvaluationDatasetError, match="YYYY-MM-DD"):
            load_dataset(self._write(tmp_path, [entry]))

    def test_bad_workload_is_rejected(self, tmp_path) -> None:
        entry = self._valid_entry()
        entry["plan_workload_hours"] = "many"
        with pytest.raises(EvaluationDatasetError, match="number"):
            load_dataset(self._write(tmp_path, [entry]))


class TestTheRunner:
    def test_a_broken_golden_response_fails_with_detail(self) -> None:
        result = run_case(
            _case(expected_response='[{"name": ""}]')
        )
        assert result.case_id == "case-x"
        assert not result.passed
        assert "ProposalParseError" in result.detail

    def test_an_unresolvable_outcome_reference_fails(self) -> None:
        result = run_case(
            _case(
                operation="task-generation",
                outcome_titles=("Aerobic base built",),
                expected_response=(
                    '[{"title": "T", "outcomes": ["No such outcome"]}]'
                ),
            )
        )
        assert not result.passed
        assert "unknown outcome" in result.detail

    def test_run_dataset_rejects_non_tuples(self) -> None:
        with pytest.raises(EvaluationDatasetError, match="tuple"):
            run_dataset([])  # type: ignore[arg-type]

    def test_results_are_reproducible(self) -> None:
        first = run_dataset(load_dataset())
        second = run_dataset(load_dataset())
        assert first == second
