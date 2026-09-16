// Browser-side client for the backcast API (TASK-109).
//
// Types mirror packages/contracts/openapi.json (ADR-008). Requests
// go to /api/* on this origin and are proxied to the backend by
// next.config.ts rewrites.

/** CurrentStateResponse from the OpenAPI contract. */
export type CurrentStateView = {
  state_id: string;
  goal_id: string;
  narrative: string;
  captured_at: string;
};

/** FutureStateResponse from the OpenAPI contract. */
export type FutureStateView = {
  state_id: string;
  goal_id: string;
  description: string;
  target_date: string;
  created_at: string;
  updated_at: string;
};

/** GapDimensionResponse from the OpenAPI contract. */
export type GapDimensionView = {
  metric_name: string;
  current_value: unknown;
  target_value: unknown;
};

/** GapResponse from the OpenAPI contract. */
export type GapView = {
  gap_id: string;
  goal_id: string;
  current_state_id: string;
  future_state_id: string;
  calculated_at: string;
  dimensions: GapDimensionView[];
  narrative: string;
};

/** BackcastResponse — the intent layer one goal's UI visualizes:
 * current → gap → future. */
export type BackcastView = {
  current: CurrentStateView;
  future: FutureStateView;
  gap: GapView;
};

export type BackcastDraft = {
  current_narrative: string;
  future_description: string;
  target_date: string;
  gap_narrative?: string;
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

/** Define a goal's backcast context (pipeline steps 1–4). */
export function defineBackcast(
  goalId: string,
  draft: BackcastDraft,
): Promise<BackcastView> {
  return request<BackcastView>(`/api/goals/${goalId}/backcast`, {
    method: "POST",
    body: JSON.stringify(draft),
  });
}
