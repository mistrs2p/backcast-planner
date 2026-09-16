"""Tests for tool permissions (TASK-101).

docs/09's permission-validation and tool-allowlist guardrails: the
allowlist of AI operations, the strict construction rules, the
enforcing provider wrapper, and the environment wiring that turns a
deployment's choice into an allowlist.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backcasting.application.permission_guard import PermittedProvider
from backcasting.config import SettingsError, load_settings
from backcasting.application.context_builder import (
    OPERATION_INSTRUCTIONS,
    build_strategy_context,
)
from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import Goal
from backcasting.domain.llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCallError,
)
from backcasting.domain.tool_permissions import (
    AI_OPERATIONS,
    ToolPermissionError,
    ToolPermissions,
    all_operations,
    grant_operations,
    no_operations,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeProvider(LLMProvider):
    def __init__(self, fail=None):
        self.fail = fail
        self.requests: list[LLMRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.fail is not None:
            raise self.fail
        return LLMResponse(content="[]", model="fake-1")


class TestTheAllowlist:
    def test_the_six_operations_match_the_context_builder(self) -> None:
        """The allowlist's universe is the provider port's operation
        keys — the context builder's instruction table is that set,
        made executable."""
        assert AI_OPERATIONS == frozenset(OPERATION_INSTRUCTIONS)

    def test_grant_operations_collapses_duplicates(self) -> None:
        permissions = grant_operations(("explanation", "explanation"))
        assert permissions.allowed_operations == frozenset({"explanation"})
        assert permissions.permits("explanation")
        assert not permissions.permits("task-generation")

    def test_all_and_no_operations(self) -> None:
        assert all_operations().permits("clarification")
        assert not no_operations().permits("clarification")

    def test_unknown_operations_are_configuration_errors(self) -> None:
        with pytest.raises(ToolPermissionError, match="unknown AI operation"):
            grant_operations(("explanation", "delete-everything"))

    def test_construction_rejects_wrong_shapes(self) -> None:
        with pytest.raises(ToolPermissionError, match="frozenset"):
            ToolPermissions({"explanation"})  # type: ignore[arg-type]
        with pytest.raises(ToolPermissionError, match="non-empty strings"):
            ToolPermissions(frozenset({"", "explanation"}))

    def test_grant_rejects_non_tuples(self) -> None:
        with pytest.raises(ToolPermissionError, match="tuple"):
            grant_operations(["explanation"])  # type: ignore[arg-type]


class TestPermissionValidation:
    def test_require_passes_permitted_operations(self) -> None:
        permissions = grant_operations(("explanation",))
        permissions.require("explanation")

    def test_require_names_the_operation_and_the_allowlist(self) -> None:
        permissions = grant_operations(("explanation",))
        with pytest.raises(
            ToolPermissionError, match="'task-generation' is not permitted"
        ) as record:
            permissions.require("task-generation")
        assert "explanation" in str(record.value)

    def test_require_on_an_empty_allowlist_says_none(self) -> None:
        with pytest.raises(ToolPermissionError, match=r"allowed: none"):
            no_operations().require("explanation")

    def test_require_rejects_bad_operation_names(self) -> None:
        permissions = all_operations()
        with pytest.raises(ToolPermissionError, match="non-empty string"):
            permissions.require("   ")
        with pytest.raises(ToolPermissionError, match="at most"):
            permissions.require("x" * 101)

    def test_require_request_validates_the_request(self) -> None:
        request = _strategy_request()
        all_operations().require_request(request)
        with pytest.raises(ToolPermissionError, match="not permitted"):
            no_operations().require_request(request)
        with pytest.raises(ToolPermissionError, match="LLMRequest"):
            no_operations().require_request("request")  # type: ignore[arg-type]


class TestPermittedProvider:
    def test_permitted_requests_pass_through_transparently(self) -> None:
        inner = FakeProvider()
        guard = PermittedProvider(inner, all_operations())
        request = _strategy_request()
        response = guard.complete(request)
        assert response.content == "[]"
        assert inner.requests == [request]
        assert guard.name == "fake"

    def test_denied_operations_never_reach_the_vendor(self) -> None:
        inner = FakeProvider()
        guard = PermittedProvider(
            inner, grant_operations(("explanation",))
        )
        with pytest.raises(
            ToolPermissionError, match="'strategy-generation'"
        ):
            guard.complete(_strategy_request())
        assert inner.requests == []

    def test_vendor_faults_propagate_untouched(self) -> None:
        fault = ProviderCallError("anthropic call failed: overloaded")
        guard = PermittedProvider(FakeProvider(fail=fault), all_operations())
        with pytest.raises(ProviderCallError) as record:
            guard.complete(_strategy_request())
        assert record.value is fault

    def test_construction_validates_arguments(self) -> None:
        with pytest.raises(TypeError, match="LLMProvider"):
            PermittedProvider("provider", all_operations())  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="ToolPermissions"):
            PermittedProvider(FakeProvider(), {"explanation"})  # type: ignore[arg-type]


def _strategy_request() -> LLMRequest:
    goal = Goal(
        goal_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Run a marathon",
        created_at=CREATED,
        updated_at=CREATED,
    )
    state = CurrentState(
        state_id=uuid.uuid4(),
        goal_id=goal.goal_id,
        narrative="A comfortable 10 km week.",
        captured_at=CREATED,
    )
    future = FutureState(
        state_id=uuid.uuid4(),
        goal_id=goal.goal_id,
        description="A marathon finished.",
        target_date=datetime(2026, 10, 11, tzinfo=timezone.utc),
        created_at=CREATED,
        updated_at=CREATED,
    )
    return build_strategy_context(goal, state, future)


class TestEnvironmentWiring:
    BASE = {
        "DATABASE_URL": "postgresql+psycopg://app:app@localhost:5432/b",
        "REDIS_URL": "redis://localhost:6379/0",
        "JWT_SECRET": "a-real-secret-value",
    }

    def test_unset_permits_all(self) -> None:
        settings = load_settings(env=self.BASE)
        assert settings.ai_operations == AI_OPERATIONS

    def test_a_list_is_honored(self) -> None:
        settings = load_settings(
            env={**self.BASE, "AI_OPERATIONS": " explanation , clarification "}
        )
        assert settings.ai_operations == frozenset(
            {"explanation", "clarification"}
        )

    def test_empty_denies_all(self) -> None:
        settings = load_settings(env={**self.BASE, "AI_OPERATIONS": "  "})
        assert settings.ai_operations == frozenset()

    def test_unknown_names_fail_fast(self) -> None:
        with pytest.raises(SettingsError, match="unknown operations"):
            load_settings(
                env={**self.BASE, "AI_OPERATIONS": "explanation,nonsense"}
            )

    def test_the_allowlist_composes_with_the_guard(self) -> None:
        """The wiring arc: env → Settings → ToolPermissions → the
        enforcing provider."""
        settings = load_settings(
            env={**self.BASE, "AI_OPERATIONS": "explanation"}
        )
        permissions = ToolPermissions(settings.ai_operations)
        guard = PermittedProvider(FakeProvider(), permissions)
        with pytest.raises(ToolPermissionError):
            guard.complete(_strategy_request())
