// Browser-side client for the progress API (TASK-114).
//
// Types mirror packages/contracts/openapi.json (ADR-008). Requests
// go to /api/* on this origin and are proxied to the backend by
// next.config.ts rewrites. The latest snapshot is read server-side
// (lib/server-api); this client carries the writes.

/** ExecutionResponse from the OpenAPI contract. */
export type ExecutionView = {
  execution_id: string;
  task_id: string;
  start: string;
  end: string;
  created_at: string;
};

/** ProgressResponse from the OpenAPI contract — one snapshot plus
 * the plan's workload basis. */
export type ProgressView = {
  snapshot_id: string;
  plan_id: string;
  taken_at: string;
  task_count: number;
  completed_task_count: number;
  planned_hours: number;
  actual_hours: number;
  remaining_hours: number;
  progress: number;
  completion_rate: number;
  plan_status: string;
  plan_workload_hours: number;
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

/** Record one sitting of actual work on one of the plan's tasks. */
export function recordExecution(
  goalId: string,
  draft: { task_id: string; start: string; end: string },
): Promise<ExecutionView> {
  return request<ExecutionView>(`/api/goals/${goalId}/executions`, {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

/** Take one progress snapshot of the plan, now. */
export function takeSnapshot(goalId: string): Promise<ProgressView> {
  return request<ProgressView>(`/api/goals/${goalId}/progress`, {
    method: "POST",
  });
}
