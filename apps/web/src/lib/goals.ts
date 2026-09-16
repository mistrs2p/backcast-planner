// Browser-side client for the goals API (TASK-107).
//
// The types mirror packages/contracts/openapi.json — the generated
// contract is the source of truth (ADR-008); these are its
// TypeScript projection. Requests go to /api/* on this origin and
// are proxied to the backend by next.config.ts rewrites.

/** GoalResponse from the OpenAPI contract. */
export type Goal = {
  goal_id: string;
  user_id: string;
  title: string;
  description: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type GoalDraft = {
  user_id: string;
  title: string;
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

export function createGoal(draft: GoalDraft): Promise<Goal> {
  return request<Goal>("/api/goals", {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

export function listGoals(userId: string): Promise<Goal[]> {
  return request<Goal[]>(`/api/goals?user_id=${encodeURIComponent(userId)}`);
}
