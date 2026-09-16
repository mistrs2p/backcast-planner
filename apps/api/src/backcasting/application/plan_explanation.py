"""Plan explanation use case — the AI's plain-language voice.

docs/09's sixth operation: given the plan and its progress, explain
where the plan stands and what comes next. This use case wires it:
the context builder assembles the plan (its tasks, its workload)
and exactly one progress snapshot; the provider port carries the
request to whichever vendor is wired; the domain records the words
verbatim, tied to both the plan and the snapshot they explain.
Unlike the proposal operations there is no deterministic half to
parse into — the explanation is the product — so the record ends
the arc.

Failure is the port's one currency: vendor faults arrive as
:class:`~backcasting.domain.llm_provider.ProviderCallError` and
propagate untouched.
"""

from __future__ import annotations

from backcasting.application.context_builder import build_explanation_context
from backcasting.domain.llm_provider import LLMProvider
from backcasting.domain.plan import Plan
from backcasting.domain.plan_explanation import (
    PlanExplanation,
    PlanExplanationError,
    record_plan_explanation,
)
from backcasting.domain.progress import ProgressSnapshot
from backcasting.domain.task import Task


def explain_plan(
    plan: Plan,
    tasks: tuple[Task, ...],
    snapshot: ProgressSnapshot,
    provider: LLMProvider,
) -> PlanExplanation:
    """Ask ``provider`` to explain ``plan`` against ``snapshot`` and
    record the words.

    The snapshot must belong to the plan — an explanation read
    against another plan's numbers is a corrupted audit trail. The
    explanation carries the provider's name and the model that
    actually answered, and is returned unsaved — persistence is the
    caller's wiring.
    """
    if not isinstance(plan, Plan):
        raise PlanExplanationError("plan must be a Plan")
    if not isinstance(snapshot, ProgressSnapshot):
        raise PlanExplanationError("snapshot must be a ProgressSnapshot")
    if snapshot.plan_id != plan.plan_id:
        raise PlanExplanationError(
            "snapshot does not belong to this plan"
        )
    request = build_explanation_context(plan, tasks, snapshot)
    response = provider.complete(request)
    return record_plan_explanation(
        plan.plan_id,
        snapshot.snapshot_id,
        response.content,
        provider=provider.name,
        model=response.model,
    )
