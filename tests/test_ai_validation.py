"""Tests for AI validation (TASK-100).

docs/09's schema-validation guardrail: parsing recorded proposals
into the deterministic proposal shapes, strictly, plus the
retry-limited generation that pairs the guardrail with its
companion "retry limits".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.application.validated_generation import (
    generate_validated_outcomes,
    generate_validated_strategies,
    generate_validated_tasks,
)
from backcasting.domain.goal import Goal, create_goal
from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCallError,
)
from backcasting.domain.outcome import define_outcome
from backcasting.domain.plan import create_plan
from backcasting.domain.proposal_parsing import (
    ProposalParseError,
    parse_outcome_titles,
    parse_strategy_proposals,
    parse_task_proposals,
)
from backcasting.domain.strategy import StrategyProposal
from backcasting.domain.task import TaskProposal

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)

STRATEGY_JSON = (
    '[{"name": "Conservative build-up", "rationale": "Steady volume '
    'first"}, {"name": "Race-pace blocks", "rationale": ""}]'
)
OUTCOME_JSON = '["Aerobic base", "Race logistics"]'
TASK_JSON = (
    '[{"title": "Weekly long run", "description": "Easy pace", '
    '"duration_hours": 1.5, "deadline": "2026-09-01T06:00:00Z", '
    '"outcomes": ["Aerobic base"]}, '
    '{"title": "Register for the race"}]'
)


class TestJsonExtraction:
    def test_plain_json(self) -> None:
        assert parse_outcome_titles(OUTCOME_JSON) == (
            "Aerobic base",
            "Race logistics",
        )

    def test_fenced_block(self) -> None:
        assert parse_outcome_titles(
            "Here is what must hold:\n\n```json\n" + OUTCOME_JSON + "\n```\n"
            "Good luck."
        ) == ("Aerobic base", "Race logistics")

    def test_unfenced_payload_inside_prose(self) -> None:
        assert parse_outcome_titles(
            "Sure! The outcomes are: " + OUTCOME_JSON + " — hope that helps."
        ) == ("Aerobic base", "Race logistics")

    def test_braces_inside_strings_do_not_confuse_the_scan(self) -> None:
        assert parse_outcome_titles(
            'An odd one: ["brace } and [ bracket inside"]'
        ) == ("brace } and [ bracket inside",)

    def test_malformed_json_is_rejected(self) -> None:
        with pytest.raises(ProposalParseError, match="malformed JSON"):
            parse_outcome_titles('["unterminated')

    def test_no_payload_is_rejected(self) -> None:
        with pytest.raises(ProposalParseError, match="no JSON"):
            parse_outcome_titles("Just words, no structure.")

    def test_empty_or_oversized_input_is_rejected(self) -> None:
        with pytest.raises(ProposalParseError, match="non-empty"):
            parse_outcome_titles("   ")
        with pytest.raises(ProposalParseError, match="at most"):
            parse_outcome_titles("[" + " " * 20_001 + "]")


class TestParseStrategyProposals:
    def test_the_full_schema(self) -> None:
        proposals = parse_strategy_proposals(STRATEGY_JSON)
        assert proposals == (
            StrategyProposal("Conservative build-up", "Steady volume first"),
            StrategyProposal("Race-pace blocks", ""),
        )

    def test_name_is_required(self) -> None:
        with pytest.raises(ProposalParseError, match="'name'"):
            parse_strategy_proposals('[{"rationale": "no name"}]')

    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ProposalParseError, match="unknown keys: extra"):
            parse_strategy_proposals(
                '[{"name": "A", "extra": "surprise"}]'
            )

    def test_non_array_is_rejected(self) -> None:
        with pytest.raises(ProposalParseError, match="must be a JSON array"):
            parse_strategy_proposals('{"name": "A"}')

    def test_empty_batch_is_rejected(self) -> None:
        with pytest.raises(ProposalParseError, match="at least one"):
            parse_strategy_proposals("[]")

    def test_domain_bounds_wrap_parse_errors(self) -> None:
        with pytest.raises(ProposalParseError, match="at most"):
            parse_strategy_proposals(
                f'[{{"name": "{"x" * 201}"}}]'
            )


class TestParseOutcomeTitles:
    def test_the_schema(self) -> None:
        assert parse_outcome_titles(OUTCOME_JSON) == (
            "Aerobic base",
            "Race logistics",
        )

    def test_non_string_entries_are_rejected(self) -> None:
        with pytest.raises(ProposalParseError, match="non-empty string"):
            parse_outcome_titles('["Aerobic base", 3]')

    def test_titles_are_trimmed(self) -> None:
        assert parse_outcome_titles('["  Padded  "]') == ("Padded",)


class TestParseTaskProposals:
    def test_the_full_schema(self) -> None:
        proposals = parse_task_proposals(TASK_JSON)
        assert len(proposals) == 2
        first, second = proposals
        assert first.title == "Weekly long run"
        assert first.description == "Easy pace"
        assert first.duration == timedelta(hours=1.5)
        assert first.deadline == datetime(
            2026, 9, 1, 6, tzinfo=timezone.utc
        )
        assert first.outcome_titles == ("Aerobic base",)
        assert second.title == "Register for the race"
        assert second.duration is None
        assert second.deadline is None
        assert second.outcome_titles == ()

    def test_title_is_required(self) -> None:
        with pytest.raises(ProposalParseError, match="'title'"):
            parse_task_proposals('[{"duration_hours": 2}]')

    def test_duration_must_be_a_finite_positive_number(self) -> None:
        for bad in ("0", "-1", '"2"', "true", "1e999"):
            with pytest.raises(ProposalParseError, match="duration_hours"):
                parse_task_proposals(
                    f'[{{"title": "A", "duration_hours": {bad}}}]'
                )

    def test_deadline_must_carry_a_utc_offset(self) -> None:
        with pytest.raises(ProposalParseError, match="UTC offset"):
            parse_task_proposals(
                '[{"title": "A", "deadline": "2026-09-01T06:00:00"}]'
            )
        with pytest.raises(ProposalParseError, match="UTC offset"):
            parse_task_proposals(
                '[{"title": "A", '
                '"deadline": "2026-09-01T06:00:00+02:00"}]'
            )

    def test_outcomes_must_be_an_array_of_strings(self) -> None:
        with pytest.raises(ProposalParseError, match="'outcomes'"):
            parse_task_proposals(
                '[{"title": "A", "outcomes": "Aerobic base"}]'
            )

    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ProposalParseError, match="unknown keys"):
            parse_task_proposals('[{"title": "A", "hours": 2}]')


class FakeProvider(LLMProvider):
    def __init__(self, contents, fail=None):
        self.contents = list(contents)
        self.fail = fail
        self.requests: list[LLMRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.fail is not None:
            raise self.fail
        content = self.contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return LLMResponse(content=content, model="fake-1")


@pytest.fixture
def backcast():
    goal = Goal(
        goal_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Run a marathon",
        created_at=CREATED,
        updated_at=CREATED,
    )
    from backcasting.domain.current_state import CurrentState
    from backcasting.domain.future_state import FutureState

    state = CurrentState(
        state_id=uuid.uuid4(),
        goal_id=goal.goal_id,
        narrative="A comfortable 10 km week.",
        captured_at=CREATED,
    )
    future = FutureState(
        state_id=uuid.uuid4(),
        goal_id=goal.goal_id,
        description="A marathon finished under five hours.",
        target_date=datetime(2026, 10, 11, tzinfo=timezone.utc),
        created_at=CREATED,
        updated_at=CREATED,
    )
    return goal, state, future


class TestValidatedGeneration:
    def test_strategies_first_attempt(self, backcast) -> None:
        goal, state, future = backcast
        provider = FakeProvider([STRATEGY_JSON])
        record, proposals = generate_validated_strategies(
            goal, state, future, provider
        )
        assert record.proposal == STRATEGY_JSON
        assert record.provider == "fake"
        assert proposals[0].name == "Conservative build-up"
        assert len(provider.requests) == 1

    def test_outcomes_retry_until_valid(self, backcast) -> None:
        _, _, future = backcast
        provider = FakeProvider(
            ["Sorry, here are some thoughts instead.", OUTCOME_JSON]
        )
        record, titles = generate_validated_outcomes(future, provider)
        assert titles == ("Aerobic base", "Race logistics")
        assert record.proposal == OUTCOME_JSON
        assert len(provider.requests) == 2

    def test_retry_limit_is_enforced(self, backcast) -> None:
        _, _, future = backcast
        provider = FakeProvider(["nope", "still nope", "[]", "never asked"])
        with pytest.raises(ProposalParseError, match="within 2 attempts") as info:
            generate_validated_outcomes(future, provider, max_attempts=2)
        assert isinstance(info.value.__cause__, ProposalParseError)
        assert len(provider.requests) == 2

    def test_vendor_faults_propagate_untouched(self, backcast) -> None:
        goal, state, future = backcast
        fault = ProviderCallError("google call failed: 503")
        provider = FakeProvider([], fail=fault)
        with pytest.raises(ProviderCallError) as record:
            generate_validated_strategies(goal, state, future, provider)
        assert record.value is fault
        assert len(provider.requests) == 1

    def test_max_attempts_must_be_positive(self, backcast) -> None:
        _, _, future = backcast
        for bad in (0, -1, True, "3"):
            with pytest.raises(ValueError, match="positive integer"):
                generate_validated_outcomes(
                    future, FakeProvider([OUTCOME_JSON]), max_attempts=bad
                )


class TestTheValidatedArc:
    def test_parsed_tasks_feed_acceptance(self, backcast) -> None:
        """The arc TASK-100 exists to close: provider → verbatim
        record → schema-valid proposals → the deterministic
        acceptor, with the domain rules applied where the context
        lives."""
        from backcasting.domain.task import accept_proposed_tasks

        goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
        plan = create_plan(goal, 10 * HOUR, created_at=CREATED)
        outcomes = tuple(
            define_outcome(plan, title, created_at=CREATED)
            for title in ("Aerobic base", "Race logistics")
        )
        provider = FakeProvider(["first attempt fails", TASK_JSON])
        record, proposals = generate_validated_tasks(outcomes, provider)
        tasks = accept_proposed_tasks(
            plan, outcomes, proposals, at=CREATED
        )
        assert tasks[0].outcome_ids == frozenset({outcomes[0].outcome_id})
        assert record.plan_id == plan.plan_id
        assert record.proposal == TASK_JSON

    def test_outcomes_must_share_one_plan(self, backcast) -> None:
        goal = create_goal(uuid.uuid4(), "Run a marathon", created_at=CREATED)
        plan = create_plan(goal, 10 * HOUR, created_at=CREATED)
        other_plan = create_plan(goal, 5 * HOUR, created_at=CREATED)
        outcomes = (
            define_outcome(plan, "Aerobic base", created_at=CREATED),
            define_outcome(other_plan, "Elsewhere", created_at=CREATED),
        )
        with pytest.raises(ValueError, match="share one plan"):
            generate_validated_tasks(outcomes, FakeProvider([TASK_JSON]))

    def test_empty_outcomes_rejected(self, backcast) -> None:
        with pytest.raises(ValueError, match="at least one outcome"):
            generate_validated_tasks((), FakeProvider([TASK_JSON]))
