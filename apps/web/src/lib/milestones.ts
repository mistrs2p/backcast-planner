// Browser-side client for the milestone API (TASK-110).
//
// Types mirror packages/contracts/openapi.json (ADR-008). Requests
// go to /api/* on this origin and are proxied to the backend by
// next.config.ts rewrites.

/** MilestoneResponse from the OpenAPI contract. */
export type MilestoneView = {
  milestone_id: string;
  run_id: string;
  goal_id: string;
  title: string;
  description: string;
  target_date: string;
  created_at: string;
  updated_at: string;
};

export type MilestoneDraft = {
  title: string;
  target_date: string;
  description?: string;
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

/** Pin a checkpoint on the goal's current backcasting run. */
export function defineMilestone(
  goalId: string,
  draft: MilestoneDraft,
): Promise<MilestoneView> {
  return request<MilestoneView>(`/api/goals/${goalId}/milestones`, {
    method: "POST",
    body: JSON.stringify(draft),
  });
}
