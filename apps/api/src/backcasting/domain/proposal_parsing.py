"""Proposal parsing — the schema-validation guardrail (docs/09).

Every AI operation records its proposal verbatim
(:mod:`~backcasting.domain.goal_interpretation` and siblings);
docs/09's guardrails then demand *schema validation* before the
domain accepts anything. This module is that layer: it parses a
recorded proposal into the deterministic proposal shapes the
acceptors consume —
:class:`~backcasting.domain.strategy.StrategyProposal` tuples,
outcome titles, :class:`~backcasting.domain.task.TaskProposal`
tuples — and rejects anything that does not parse. It never
repairs: a proposal the guardrail silently fixed is a proposal the
audit trail can no longer trust (ADR-002 — the LLM proposes, the
Domain validates and enforces; validating means saying no).

The wire contract is JSON — an array of objects for strategies and
tasks, an array of strings for outcomes — because schema
validation needs a schema, and free prose has none. The proposal
may carry prose around the JSON (models like to talk); extraction
finds the payload, then the schema is enforced strictly: unknown
keys, wrong types, missing required fields, empty batches, and
non-UTC deadlines are all contract violations, not hints.

What this module does *not* do is acceptance: the parsed proposals
still pass through
:func:`~backcasting.domain.strategy.accept_proposed_strategies`
and :func:`~backcasting.domain.task.accept_proposed_tasks`, where
the domain rules (a RUNNING run, a living plan, unique titles,
resolvable outcome references) apply with the context only the
caller holds.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from backcasting.domain.strategy import StrategyProposal
from backcasting.domain.task import TaskProposal

MAX_PROPOSAL_TEXT_LENGTH = 20_000


class ProposalParseError(ValueError):
    """Raised when a proposal does not satisfy its JSON schema."""


def _extract_json(proposal: str) -> Any:
    """Find the JSON payload in ``proposal``.

    Tried in order: the whole text; the first fenced code block; the
    first balanced ``[...]``/``{...}`` span. All failures are
    :class:`ProposalParseError` — never a repaired guess.
    """
    if (
        not isinstance(proposal, str)
        or not proposal.strip()
        or len(proposal) > MAX_PROPOSAL_TEXT_LENGTH
    ):
        raise ProposalParseError(
            "proposal must be a non-empty string of at most "
            f"{MAX_PROPOSAL_TEXT_LENGTH} characters"
        )
    try:
        return json.loads(proposal)
    except ValueError:
        pass
    fenced = _first_fenced_block(proposal)
    if fenced is not None:
        try:
            return json.loads(fenced)
        except ValueError:
            pass
    span, found_opening = _first_balanced_span(proposal)
    if span is not None:
        try:
            return json.loads(span)
        except ValueError as error:
            raise ProposalParseError(
                f"proposal contains malformed JSON: {error}"
            ) from error
    if found_opening:
        raise ProposalParseError(
            "proposal contains malformed JSON: unbalanced brackets"
        )
    raise ProposalParseError("proposal contains no JSON payload")


def _first_fenced_block(proposal: str) -> str | None:
    start = proposal.find("```")
    if start == -1:
        return None
    first_newline = proposal.find("\n", start)
    end = proposal.find("```", start + 3)
    if first_newline == -1 or end == -1 or end < first_newline:
        return None
    return proposal[first_newline + 1 : end]


def _first_balanced_span(proposal: str) -> tuple[str | None, bool]:
    """The first balanced ``[...]``/``{...}`` span, or ``None`` —
    and whether any opening bracket existed at all (an unbalanced
    opening is malformed JSON, not a missing payload)."""
    opening = -1
    for index, char in enumerate(proposal):
        if char in "[{":
            opening = index
            break
    if opening == -1:
        return None, False
    closer = "]" if proposal[opening] == "[" else "}"
    depth = 0
    in_string = False
    escaped = False
    for index in range(opening, len(proposal)):
        char = proposal[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                if char != closer:
                    return None, True
                return proposal[opening : index + 1], True
    return None, True


def _require_array(payload: Any, what: str) -> list[Any]:
    if not isinstance(payload, list):
        raise ProposalParseError(
            f"{what} must be a JSON array, got {type(payload).__name__}"
        )
    if not payload:
        raise ProposalParseError(
            f"{what} must contain at least one entry — an empty "
            "generation is a failed step, not a valid proposal"
        )
    return payload


def _require_object(entry: Any, what: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ProposalParseError(
            f"each {what} must be a JSON object, got "
            f"{type(entry).__name__}"
        )
    return entry


def _reject_unknown_keys(entry: dict[str, Any], allowed: set[str], what: str) -> None:
    unknown = sorted(set(entry) - allowed)
    if unknown:
        raise ProposalParseError(
            f"{what} contains unknown keys: {', '.join(unknown)}"
        )


def _require_string(entry: dict[str, Any], key: str, what: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProposalParseError(
            f"{what} requires a non-empty string '{key}'"
        )
    return value


def _optional_string(entry: dict[str, Any], key: str, what: str) -> str:
    if key not in entry or entry[key] is None:
        return ""
    value = entry[key]
    if not isinstance(value, str):
        raise ProposalParseError(f"{what} '{key}' must be a string")
    return value


def _parse_deadline(value: Any, what: str) -> datetime:
    if not isinstance(value, str):
        raise ProposalParseError(f"{what} 'deadline' must be an ISO-8601 string")
    try:
        deadline = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProposalParseError(
            f"{what} 'deadline' is not a valid ISO-8601 datetime: {value!r}"
        ) from error
    if deadline.tzinfo is None or deadline.utcoffset() != timedelta(0):
        raise ProposalParseError(
            f"{what} 'deadline' must carry a UTC offset: {value!r}"
        )
    return deadline.astimezone(timezone.utc)


def _parse_duration(value: Any, what: str) -> timedelta:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProposalParseError(f"{what} 'duration_hours' must be a number")
    hours = float(value)
    if not math.isfinite(hours) or hours <= 0:
        raise ProposalParseError(
            f"{what} 'duration_hours' must be a finite positive number"
        )
    return timedelta(hours=hours)


def _parse_title_list(value: Any, what: str, key: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProposalParseError(f"{what} '{key}' must be an array of strings")
    titles: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ProposalParseError(
                f"{what} '{key}' must contain non-empty strings"
            )
        titles.append(item.strip())
    return tuple(titles)


def parse_strategy_proposals(proposal: str) -> tuple[StrategyProposal, ...]:
    """Parse a strategy generation's proposal into
    :class:`~backcasting.domain.strategy.StrategyProposal` tuples.

    Schema: ``[{"name": str, "rationale"?: str}, ...]`` — at least
    one entry; ``name`` required, ``rationale`` optional; unknown
    keys rejected. The :class:`StrategyProposal` constructor
    enforces the domain bounds (name ≤200, rationale ≤5000).
    """
    payload = _extract_json(proposal)
    entries = _require_array(payload, "strategy proposal")
    proposals: list[StrategyProposal] = []
    for index, entry in enumerate(entries):
        what = f"strategy proposal entry {index}"
        _reject_unknown_keys(entry if isinstance(entry, dict) else {}, {"name", "rationale"}, what)
        try:
            proposals.append(
                StrategyProposal(
                    name=_require_string(entry, "name", what),
                    rationale=_optional_string(entry, "rationale", what),
                )
            )
        except ValueError as error:
            raise ProposalParseError(f"{what}: {error}") from error
    return tuple(proposals)


def parse_outcome_titles(proposal: str) -> tuple[str, ...]:
    """Parse an outcome decomposition's proposal into outcome
    titles.

    Schema: ``["title", ...]`` — at least one non-empty string. The
    titles feed
    :func:`~backcasting.domain.outcome.define_outcome` one by one;
    uniqueness is the plan's rule to enforce, not the schema's.
    """
    payload = _extract_json(proposal)
    entries = _require_array(payload, "outcome proposal")
    titles: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, str) or not entry.strip():
            raise ProposalParseError(
                f"outcome proposal entry {index} must be a non-empty string"
            )
        titles.append(entry.strip())
    return tuple(titles)


def parse_task_proposals(proposal: str) -> tuple[TaskProposal, ...]:
    """Parse a task generation's proposal into
    :class:`~backcasting.domain.task.TaskProposal` tuples.

    Schema: ``[{"title": str, "description"?: str,
    "duration_hours"?: number, "deadline"?:
    "YYYY-MM-DDTHH:MM:SS+00:00", "outcomes"?: [str]}, ...]`` — at
    least one entry; only ``title`` is required; unknown keys
    rejected; a deadline without a UTC offset is a contract
    violation. The :class:`TaskProposal` constructor enforces the
    domain bounds.
    """
    payload = _extract_json(proposal)
    entries = _require_array(payload, "task proposal")
    proposals: list[TaskProposal] = []
    for index, entry in enumerate(entries):
        what = f"task proposal entry {index}"
        _reject_unknown_keys(
            entry if isinstance(entry, dict) else {},
            {"title", "description", "duration_hours", "deadline", "outcomes"},
            what,
        )
        duration = (
            _parse_duration(entry["duration_hours"], what)
            if "duration_hours" in entry and entry["duration_hours"] is not None
            else None
        )
        deadline = (
            _parse_deadline(entry["deadline"], what)
            if "deadline" in entry and entry["deadline"] is not None
            else None
        )
        outcome_titles = (
            _parse_title_list(entry["outcomes"], what, "outcomes")
            if "outcomes" in entry and entry["outcomes"] is not None
            else ()
        )
        try:
            proposals.append(
                TaskProposal(
                    title=_require_string(entry, "title", what),
                    description=_optional_string(entry, "description", what),
                    duration=duration,
                    deadline=deadline,
                    outcome_titles=outcome_titles,
                )
            )
        except ValueError as error:
            raise ProposalParseError(f"{what}: {error}") from error
    return tuple(proposals)
