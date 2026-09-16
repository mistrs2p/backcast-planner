// Browser-side client for the replanning API (TASK-115).
//
// Types mirror packages/contracts/openapi.json (ADR-008). Requests
// go to /api/* on this origin and are proxied to the backend by
// next.config.ts rewrites. The version trail is read server-side
// (lib/server-api); this client carries the replans themselves.

import type { PlanView, TaskView } from "@/lib/plans";

/** PlanVersionResponse from the OpenAPI contract — one traceable
 * version: why the plan changed, from which run (if any), and what
 * changed (new values, null when untouched). */
export type PlanVersionView = {
  version_id: string;
  plan_id: string;
  version: number;
  reason: string;
  title: string | null;
  workload_hours: number | null;
  revised_task_ids: string[];
  source_run_id: string | null;
  created_at: string;
};

/** LocalReplanResponse — the plan after the revision, the revised
 * task, and the version tracing it. */
export type LocalReplanResult = {
  plan: PlanView;
  task: TaskView;
  version: PlanVersionView;
};

/** GlobalReplanResponse — the re-derived plan and the version
 * tracing it. */
export type GlobalReplanResult = {
  plan: PlanView;
  version: PlanVersionView;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // not JSON — keep the status line
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

/** Revise one task of the goal's plan in place (LOCAL scope) — the
 * archetypal re-estimate — traced as a plan version. Omitted fields
 * keep their current value. */
export function replanTaskLocally(
  goalId: string,
  draft: {
    task_id: string;
    reason: string;
    title?: string;
    description?: string;
    duration_hours?: number;
    deadline?: string;
  },
): Promise<LocalReplanResult> {
  return request<LocalReplanResult>(
    `/api/goals/${goalId}/plan/replan/local`,
    {
      method: "POST",
      body: JSON.stringify(draft),
    },
  );
}

/** Re-derive the goal's plan from its task set (GLOBAL scope):
 * workload recomputed, title optionally revised, traced as a plan
 * version. */
export function replanPlanGlobally(
  goalId: string,
  draft: { reason: string; title?: string },
): Promise<GlobalReplanResult> {
  return request<GlobalReplanResult>(
    `/api/goals/${goalId}/plan/replan/global`,
    {
      method: "POST",
      body: JSON.stringify(draft),
    },
  );
}
