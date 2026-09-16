// Browser-side client for the plan API (TASK-111).
//
// Types mirror packages/contracts/openapi.json (ADR-008). Requests
// go to /api/* on this origin and are proxied to the backend by
// next.config.ts rewrites.

/** PlanResponse from the OpenAPI contract. */
export type PlanView = {
  plan_id: string;
  goal_id: string;
  run_id: string | null;
  title: string;
  status: string;
  workload_hours: number;
  created_at: string;
  updated_at: string;
};

/** OutcomeResponse from the OpenAPI contract. */
export type OutcomeView = {
  outcome_id: string;
  plan_id: string;
  title: string;
  description: string;
  milestone_id: string | null;
  created_at: string;
  updated_at: string;
};

/** TaskResponse from the OpenAPI contract. */
export type TaskView = {
  task_id: string;
  plan_id: string;
  title: string;
  description: string;
  duration_hours: number | null;
  deadline: string | null;
  outcome_ids: string[];
  created_at: string;
  updated_at: string;
};

/** PlanBundleResponse — the plan UI's view. */
export type PlanBundleView = {
  plan: PlanView;
  outcomes: OutcomeView[];
  tasks: TaskView[];
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

/** Finish the goal's run and open a DRAFT plan from it. */
export function beginPlan(
  goalId: string,
  title: string,
): Promise<PlanBundleView> {
  return request<PlanBundleView>(`/api/goals/${goalId}/plan`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

/** Define an outcome on the goal's DRAFT plan. */
export function addOutcome(
  goalId: string,
  draft: { title: string; description?: string; milestone_id?: string },
): Promise<OutcomeView> {
  return request<OutcomeView>(`/api/goals/${goalId}/plan/outcomes`, {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

/** Add a task to the goal's DRAFT plan. */
export function addTask(
  goalId: string,
  draft: {
    title: string;
    description?: string;
    duration_hours?: number;
    deadline?: string;
    outcome_ids?: string[];
  },
): Promise<TaskView> {
  return request<TaskView>(`/api/goals/${goalId}/plan/tasks`, {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

/** Revise a task on the goal's DRAFT plan (TASK-112) — omitted
 * fields keep their current value. */
export function reviseTask(
  goalId: string,
  taskId: string,
  changes: {
    title?: string;
    description?: string;
    duration_hours?: number;
    deadline?: string;
  },
): Promise<TaskView> {
  return request<TaskView>(`/api/goals/${goalId}/plan/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

/** Close the DRAFT plan into a CANDIDATE with its workload. */
export function publishPlan(goalId: string): Promise<PlanBundleView> {
  return request<PlanBundleView>(`/api/goals/${goalId}/plan/publish`, {
    method: "POST",
  });
}
