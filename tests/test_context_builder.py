"""Tests for the context builder (TASK-094).

docs/09's context strategy made structural: each operation's
composer takes exactly the records that operation needs, the
sections render under headings, and unknown operations have no
fallback instruction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.context_builder import (
    ContextBuilderError,
    ContextSection,
    build_clarification_context,
    build_context,
    build_explanation_context,
    build_goal_interpretation_context,
    build_outcome_decomposition_context,
    build_strategy_context,
    build_task_generation_context,
    current_state_section,
    future_state_section,
    goal_section,
    outcomes_section,
    plan_section,
    progress_section,
)
from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import create_goal
from backcasting.domain.llm_provider import LLMRequest, MessageRole
from backcasting.domain.outcome import Outcome
from backcasting.domain.plan import create_plan
from backcasting.domain.progress import take_progress_snapshot
from backcasting.domain.task import create_task, revise_task

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


@pytest.fixture
def goal():
    return create_goal(
        uuid.uuid4(), "Run a marathon", description="Finish upright.",
        created_at=CREATED,
    )


@pytest.fixture
def current():
    return CurrentState(
        state_id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        narrative="Couch-bound; 30-minute walks feel long.",
        captured_at=CREATED,
    )


@pytest.fixture
def future():
    return FutureState(
        state_id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        description="A marathon finished under five hours.",
        target_date=datetime(2026, 10, 11, tzinfo=timezone.utc),
        created_at=CREATED,
        updated_at=CREATED,
    )


class TestContextSection:
    def test_shape_and_render(self) -> None:
        section = ContextSection("Goal", "Run a marathon.")
        assert section.render() == "## Goal\nRun a marathon."

    def test_rejects_empty_fields(self) -> None:
        with pytest.raises(ContextBuilderError, match="heading"):
            ContextSection("  ", "Body")
        with pytest.raises(ContextBuilderError, match="body"):
            ContextSection("Goal", "  ")
        with pytest.raises(ContextBuilderError, match="heading"):
            ContextSection(42, "Body")  # type: ignore[arg-type]


class TestBuildContext:
    def test_assembles_system_and_user_messages(self) -> None:
        request = build_context(
            "goal-interpretation",
            (ContextSection("Goal", "Run a marathon."),),
        )
        assert isinstance(request, LLMRequest)
        assert request.operation == "goal-interpretation"
        assert [m.role for m in request.messages] == [
            MessageRole.SYSTEM, MessageRole.USER,
        ]
        system, user = request.messages
        assert "Interpret the user's goal" in system.content
        assert system.content.endswith("the system validates and enforces.")
        assert user.content == "## Goal\nRun a marathon."

    def test_sections_render_in_order_joined_by_blank_lines(self) -> None:
        request = build_context(
            "strategy-generation",
            (
                ContextSection("Goal", "Run."),
                ContextSection("Current state", "Couch."),
                ContextSection("Future state", "Marathon."),
            ),
        )
        assert request.messages[1].content == (
            "## Goal\nRun.\n\n## Current state\nCouch.\n\n"
            "## Future state\nMarathon."
        )

    def test_every_docs_09_operation_has_an_instruction(self) -> None:
        from backcasting.application.context_builder import OPERATION_INSTRUCTIONS

        assert set(OPERATION_INSTRUCTIONS) == {
            "goal-interpretation",
            "clarification",
            "strategy-generation",
            "outcome-decomposition",
            "task-generation",
            "explanation",
        }

    def test_unknown_operations_have_no_fallback(self) -> None:
        """A generic instruction would silently produce unspecific
        context — the exact failure the strategy forbids."""
        with pytest.raises(ContextBuilderError, match="unknown operation"):
            build_context("summarize-everything", (ContextSection("A", "B"),))

    def test_sections_are_mandatory(self) -> None:
        with pytest.raises(ContextBuilderError, match="must not be empty"):
            build_context("goal-interpretation", ())
        with pytest.raises(ContextBuilderError, match="must be a tuple"):
            build_context("goal-interpretation", [ContextSection("A", "B")])  # type: ignore[arg-type]
        with pytest.raises(ContextBuilderError, match="ContextSection instances"):
            build_context("goal-interpretation", ("section",))  # type: ignore[arg-type]

    def test_sampling_knobs_carry_through(self) -> None:
        request = build_context(
            "clarification",
            (ContextSection("Goal", "Run."),),
            model="gpt-5.1",
            max_output_tokens=256,
            temperature=0.1,
        )
        assert request.model == "gpt-5.1"
        assert request.max_output_tokens == 256
        assert request.temperature == 0.1


class TestRecordRenderers:
    def test_goal_section_selects_title_and_description(self, goal) -> None:
        assert goal_section(goal).render() == (
            "## Goal\nRun a marathon\n\nFinish upright."
        )

    def test_goal_section_without_description(self, goal) -> None:
        bare = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
        assert goal_section(bare).render() == "## Goal\nRun a marathon"

    def test_goal_section_rejects_other_types(self, current) -> None:
        with pytest.raises(ContextBuilderError, match="must be a Goal"):
            goal_section(current)  # type: ignore[arg-type]

    def test_current_state_section(self, current) -> None:
        assert current_state_section(current).render() == (
            "## Current state\nCouch-bound; 30-minute walks feel long."
        )

    def test_future_state_section_includes_the_target_date(self, future) -> None:
        rendered = future_state_section(future).render()
        assert "A marathon finished under five hours." in rendered
        assert "Target date: 2026-10-11" in rendered

    def test_outcomes_section_lists_titles_with_descriptions(self) -> None:
        outcome = Outcome(
            outcome_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),
            title="Base built",
            description="A 40 km week, comfortably.",
            created_at=CREATED,
            updated_at=CREATED,
        )
        bare = Outcome(
            outcome_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),
            title="Race registered",
            created_at=CREATED,
            updated_at=CREATED,
        )
        assert outcomes_section((outcome, bare)).render() == (
            "## Outcomes\n- Base built: A 40 km week, comfortably.\n"
            "- Race registered"
        )

    def test_outcomes_section_requires_content(self) -> None:
        with pytest.raises(ContextBuilderError, match="must not be empty"):
            outcomes_section(())

    def test_plan_section_lists_tasks_with_durations(self, goal) -> None:
        plan = create_plan(goal, 7 * HOUR, created_at=CREATED)
        run = revise_task(
            create_task(plan, "Long run", created_at=CREATED),
            duration=2 * HOUR, updated_at=CREATED,
        )
        later = create_task(plan, "Register", created_at=CREATED)
        rendered = plan_section(plan, (run, later)).render()
        assert "Total workload: 7 hours" in rendered
        assert "1. Long run (2 hours)" in rendered
        assert "2. Register (no estimate yet)" in rendered

    def test_plan_section_with_title(self, goal) -> None:
        plan = create_plan(goal, 7 * HOUR, title="Marathon plan", created_at=CREATED)
        rendered = plan_section(plan, ()).render()
        assert rendered.startswith("## Plan\nMarathon plan\n")
        assert "Total workload: 7 hours" in rendered

    def test_progress_section_states_the_numbers(self, goal) -> None:
        plan = create_plan(goal, 9 * HOUR, created_at=CREATED)
        task = revise_task(
            create_task(plan, "Run", created_at=CREATED),
            duration=9 * HOUR, updated_at=CREATED,
        )
        snapshot = take_progress_snapshot(plan, (task,), (), at=CREATED)
        rendered = progress_section(snapshot).render()
        assert rendered == (
            "## Progress\nPlanned: 9 hours\nActually worked: 0 hours\n"
            "Remaining: 9 hours\nTasks completed: 0 of 1"
        )


class TestOperationComposers:
    def test_goal_interpretation_gets_goal_and_current_state(
        self, goal, current
    ) -> None:
        request = build_goal_interpretation_context(goal, current)
        assert request.operation == "goal-interpretation"
        assert "## Goal" in request.messages[1].content
        assert "## Current state" in request.messages[1].content

    def test_clarification_gets_the_same_minimal_context(
        self, goal, current
    ) -> None:
        request = build_clarification_context(goal, current)
        assert request.operation == "clarification"
        assert request.messages[1].content.count("##") == 2

    def test_strategy_gets_all_three_anchors(self, goal, current, future) -> None:
        request = build_strategy_context(goal, current, future)
        assert request.operation == "strategy-generation"
        body = request.messages[1].content
        assert "## Goal" in body
        assert "## Current state" in body
        assert "## Future state" in body

    def test_outcome_decomposition_gets_only_the_future(self, future) -> None:
        request = build_outcome_decomposition_context(future)
        assert request.operation == "outcome-decomposition"
        assert request.messages[1].content.count("##") == 1
        assert "## Future state" in request.messages[1].content

    def test_task_generation_gets_only_the_outcomes(self) -> None:
        outcome = Outcome(
            outcome_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),
            title="Base built",
            created_at=CREATED,
            updated_at=CREATED,
        )
        request = build_task_generation_context((outcome,))
        assert request.operation == "task-generation"
        assert "## Outcomes" in request.messages[1].content

    def test_explanation_gets_plan_and_progress(self, goal) -> None:
        plan = create_plan(goal, 9 * HOUR, created_at=CREATED)
        task = revise_task(
            create_task(plan, "Run", created_at=CREATED),
            duration=9 * HOUR, updated_at=CREATED,
        )
        snapshot = take_progress_snapshot(plan, (task,), (), at=CREATED)
        request = build_explanation_context(plan, (task,), snapshot)
        assert request.operation == "explanation"
        body = request.messages[1].content
        assert "## Plan" in body
        assert "## Progress" in body


class TestWiring:
    def test_context_flows_straight_into_a_provider(self, goal, current) -> None:
        """The builder's output is a complete request: the operations
        hand it to any vendor unchanged."""
        from backcasting.domain.llm_provider import (
            LLMProvider,
            LLMResponse,
        )

        class _Echo(LLMProvider):
            @property
            def name(self) -> str:
                return "echo"

            def complete(self, request):
                return LLMResponse(
                    content=f"Proposal for {request.operation}.", model="echo-1"
                )

        provider = _Echo()
        request = build_goal_interpretation_context(goal, current)
        response = provider.complete(request)
        assert response.content == "Proposal for goal-interpretation."
