"""Tests for the repository interfaces (TASK-019).

The ports themselves are abstract; these tests pin the contract shape
(abstract instantiation, method surface, error type) and exercise the
conventions through an in-memory fake — insert-or-replace keyed by entity
id, None for absence, and the ordering guarantees the domain relies on.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.current_state import CurrentState, capture_current_state
from backcasting.domain.future_state import FutureState, define_future_state
from backcasting.domain.goal import Goal, create_goal
from backcasting.domain.repositories import (
    CurrentStateRepository,
    FutureStateRepository,
    GoalRepository,
    RepositoryError,
    UserRepository,
)
from backcasting.domain.user import Email, User, create_user

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        self._users: dict[uuid.UUID, User] = {}

    def save(self, user: User) -> None:
        self._users[user.user_id] = user

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._users.get(user_id)

    def get_by_email(self, email: Email) -> User | None:
        for user in self._users.values():
            if user.email == email:
                return user
        return None


class InMemoryGoalRepository(GoalRepository):
    def __init__(self) -> None:
        self._goals: dict[uuid.UUID, Goal] = {}

    def save(self, goal: Goal) -> None:
        self._goals[goal.goal_id] = goal

    def get(self, goal_id: uuid.UUID) -> Goal | None:
        return self._goals.get(goal_id)

    def list_for_user(self, user_id: uuid.UUID) -> list[Goal]:
        return [
            goal
            for goal in sorted(self._goals.values(), key=lambda g: g.created_at)
            if goal.user_id == user_id
        ]


class InMemoryCurrentStateRepository(CurrentStateRepository):
    def __init__(self) -> None:
        self._states: dict[uuid.UUID, CurrentState] = {}

    def save(self, state: CurrentState) -> None:
        self._states[state.state_id] = state

    def get(self, state_id: uuid.UUID) -> CurrentState | None:
        return self._states.get(state_id)

    def list_for_goal(self, goal_id: uuid.UUID) -> list[CurrentState]:
        return [
            state
            for state in sorted(
                self._states.values(), key=lambda s: s.captured_at
            )
            if state.goal_id == goal_id
        ]

    def latest_for_goal(self, goal_id: uuid.UUID) -> CurrentState | None:
        states = self.list_for_goal(goal_id)
        return states[-1] if states else None


class InMemoryFutureStateRepository(FutureStateRepository):
    def __init__(self) -> None:
        self._states: dict[uuid.UUID, FutureState] = {}

    def save(self, state: FutureState) -> None:
        self._states[state.state_id] = state

    def get(self, state_id: uuid.UUID) -> FutureState | None:
        return self._states.get(state_id)

    def get_for_goal(self, goal_id: uuid.UUID) -> FutureState | None:
        matches = [s for s in self._states.values() if s.goal_id == goal_id]
        return matches[0] if matches else None


class TestContractShape:
    @pytest.mark.parametrize(
        "repo_class",
        [UserRepository, GoalRepository, CurrentStateRepository, FutureStateRepository],
    )
    def test_interfaces_cannot_be_instantiated(self, repo_class: type) -> None:
        with pytest.raises(TypeError):
            repo_class()  # type: ignore[abstract]

    def test_repository_error_is_a_runtime_error(self) -> None:
        assert issubclass(RepositoryError, RuntimeError)

    @pytest.mark.parametrize(
        "repo_class,methods",
        [
            (UserRepository, ["save", "get", "get_by_email"]),
            (GoalRepository, ["save", "get", "list_for_user"]),
            (
                CurrentStateRepository,
                ["save", "get", "list_for_goal", "latest_for_goal"],
            ),
            (FutureStateRepository, ["save", "get", "get_for_goal"]),
        ],
    )
    def test_method_surface(self, repo_class: type, methods: list[str]) -> None:
        for method in methods:
            assert callable(getattr(repo_class, method)), method


class TestUserPort:
    def test_save_and_get_round_trip(self) -> None:
        repo = InMemoryUserRepository()
        user = create_user("user@example.com", "Ada")
        repo.save(user)
        assert repo.get(user.user_id) is user

    def test_get_by_email_finds_normalized_address(self) -> None:
        repo = InMemoryUserRepository()
        user = create_user("user@EXAMPLE.com", "Ada")
        repo.save(user)
        assert repo.get_by_email(Email("user@example.com")) is user

    def test_absent_user_returns_none(self) -> None:
        repo = InMemoryUserRepository()
        assert repo.get(uuid.uuid4()) is None
        assert repo.get_by_email(Email("nobody@example.com")) is None

    def test_save_replaces_by_identity(self) -> None:
        repo = InMemoryUserRepository()
        user = create_user("user@example.com", "Ada")
        repo.save(user)
        renamed = User(
            user_id=user.user_id,
            email=user.email,
            display_name="Ada Lovelace",
            timezone=user.timezone,
            created_at=user.created_at,
        )
        repo.save(renamed)
        assert repo.get(user.user_id) is renamed


class TestGoalPort:
    def test_save_and_get_round_trip(self) -> None:
        repo = InMemoryGoalRepository()
        goal = create_goal(uuid.uuid4(), "Run a marathon")
        repo.save(goal)
        assert repo.get(goal.goal_id) is goal

    def test_list_for_user_filters_and_orders(self) -> None:
        repo = InMemoryGoalRepository()
        user_id = uuid.uuid4()
        other_id = uuid.uuid4()
        second = create_goal(user_id, "Second", created_at=BASE + timedelta(days=1))
        first = create_goal(user_id, "First", created_at=BASE)
        unrelated = create_goal(other_id, "Unrelated", created_at=BASE)
        for goal in (second, first, unrelated):
            repo.save(goal)
        assert repo.list_for_user(user_id) == [first, second]

    def test_absent_goal_returns_none(self) -> None:
        assert InMemoryGoalRepository().get(uuid.uuid4()) is None


class TestCurrentStatePort:
    def test_save_and_get_round_trip(self) -> None:
        repo = InMemoryCurrentStateRepository()
        state = capture_current_state(uuid.uuid4(), "Reality.")
        repo.save(state)
        assert repo.get(state.state_id) is state

    def test_list_orders_by_capture_time(self) -> None:
        repo = InMemoryCurrentStateRepository()
        goal_id = uuid.uuid4()
        later = capture_current_state(
            goal_id, "Later.", captured_at=BASE + timedelta(days=2)
        )
        earlier = capture_current_state(
            goal_id, "Earlier.", captured_at=BASE + timedelta(days=1)
        )
        unrelated = capture_current_state(
            uuid.uuid4(), "Unrelated.", captured_at=BASE
        )
        for state in (later, earlier, unrelated):
            repo.save(state)
        assert repo.list_for_goal(goal_id) == [earlier, later]

    def test_latest_for_goal(self) -> None:
        repo = InMemoryCurrentStateRepository()
        goal_id = uuid.uuid4()
        earlier = capture_current_state(
            goal_id, "Earlier.", captured_at=BASE
        )
        later = capture_current_state(
            goal_id, "Later.", captured_at=BASE + timedelta(days=1)
        )
        repo.save(earlier)
        repo.save(later)
        assert repo.latest_for_goal(goal_id) is later

    def test_latest_for_goal_without_snapshots_is_none(self) -> None:
        assert InMemoryCurrentStateRepository().latest_for_goal(uuid.uuid4()) is None


class TestFutureStatePort:
    def test_save_and_get_round_trip(self) -> None:
        repo = InMemoryFutureStateRepository()
        state = define_future_state(
            uuid.uuid4(),
            "Destination.",
            BASE + timedelta(days=30),
            created_at=BASE,
        )
        repo.save(state)
        assert repo.get(state.state_id) is state

    def test_get_for_goal(self) -> None:
        repo = InMemoryFutureStateRepository()
        goal_id = uuid.uuid4()
        state = define_future_state(
            goal_id,
            "Destination.",
            BASE + timedelta(days=30),
            created_at=BASE,
        )
        repo.save(state)
        assert repo.get_for_goal(goal_id) is state

    def test_get_for_goal_without_destination_is_none(self) -> None:
        assert InMemoryFutureStateRepository().get_for_goal(uuid.uuid4()) is None
