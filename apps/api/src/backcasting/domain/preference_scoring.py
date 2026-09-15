"""Preference scoring for candidate slots.

The soft layer of the scheduling hierarchy (docs/05): "… → deadline
→ soft preferences → optimization". Everything before this point was
subtractive — hard constraints, commitments, dependencies, deadlines
removed or clipped candidates. Preferences never remove anything: a
slot with a terrible score is still schedulable, merely ranked last.

Scoring is deterministic and combines the three things a Preference
carries (TASK-043): direction, weight, and overlap. Each preference
contributes its ``weight`` scaled by the fraction of the slot that
falls inside its window — positive for ``PREFER``, negative for
``AVOID`` — and the slot's score is the sum of the contributions.
Half of a weight-5 window is worth half of a fully-covered weight-5
window, and an ``AVOID`` at weight 5 exactly cancels a ``PREFER`` at
weight 5 over the same time.

Ranking is a stable sort by descending score: candidates equal in
the eyes of the preferences keep their input order, so generation
order (chronological, per :func:`generate_candidate_slots`) remains
the tie-breaker.
"""

from __future__ import annotations

from datetime import timedelta

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.preference import Preference, PreferenceDirection, preference_windows


class PreferenceScoringError(ValueError):
    """Raised when a preference-scoring invariant is violated."""


def _validate_preferences(preferences) -> None:
    if not isinstance(preferences, tuple):
        raise PreferenceScoringError("preferences must be a tuple of Preference")
    for preference in preferences:
        if not isinstance(preference, Preference):
            raise PreferenceScoringError("preferences must be Preference instances")


def _overlap_with_windows(slot: CandidateSlot, preference: Preference) -> timedelta:
    """Total time ``slot`` spends inside ``preference``'s windows.

    Windows of a single preference never overlap one another, so a
    plain sum is exact. Half-open semantics throughout.
    """
    total = timedelta(0)
    for window_start, window_end in preference_windows(
        preference, range_start=slot.start, range_end=slot.end
    ):
        overlap_start = max(slot.start, window_start)
        overlap_end = min(slot.end, window_end)
        if overlap_start < overlap_end:
            total += overlap_end - overlap_start
    return total


def score_slot(slot: CandidateSlot, preferences: tuple[Preference, ...]) -> float:
    """The deterministic preference score of ``slot`` — higher is better.

    Each preference contributes ``±weight × (overlap / slot duration)``
    (+ for ``PREFER``, − for ``AVOID``); the score is the sum. With no
    preferences every slot scores 0.0 — the soft layer abstains, it
    never reorders by default.
    """
    if not isinstance(slot, CandidateSlot):
        raise PreferenceScoringError("slot must be a CandidateSlot")
    _validate_preferences(preferences)

    duration = slot.duration
    score = 0.0
    for preference in preferences:
        overlap = _overlap_with_windows(slot, preference)
        if overlap <= timedelta(0):
            continue
        contribution = preference.weight * (overlap / duration)
        if preference.direction is PreferenceDirection.AVOID:
            contribution = -contribution
        score += contribution
    return score


def rank_slots_by_preferences(
    slots: tuple[CandidateSlot, ...],
    preferences: tuple[Preference, ...],
) -> tuple[CandidateSlot, ...]:
    """Order ``slots`` best-first by preference score.

    A pure ranking: every input slot appears in the output —
    preferences guide the optimizer's choice, they never reject a
    candidate (docs/05). Equal scores keep input order (stable sort),
    so chronological generation order remains the tie-breaker.
    """
    if not isinstance(slots, tuple):
        raise PreferenceScoringError("slots must be a tuple of CandidateSlot")
    for slot in slots:
        if not isinstance(slot, CandidateSlot):
            raise PreferenceScoringError("slots must be CandidateSlot instances")
    _validate_preferences(preferences)

    return tuple(sorted(slots, key=lambda slot: -score_slot(slot, preferences)))
