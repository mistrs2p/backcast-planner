// Browser-side client for the AI assistant API (TASK-116).
//
// Types mirror packages/contracts/openapi.json (ADR-008). Requests
// go to /api/* on this origin and are proxied to the backend by
// next.config.ts rewrites. The reading history is read server-side
// (lib/server-api); this client carries the ask.

/** InterpretationResponse from the OpenAPI contract — one AI
 * proposal reading a goal, with the provider and model that
 * actually answered. */
export type InterpretationView = {
  interpretation_id: string;
  goal_id: string;
  proposal: string;
  provider: string;
  model: string;
  created_at: string;
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

/** Ask the wired AI provider to read the goal against its current
 * state. The server answers 503 when no provider is configured —
 * that message surfaces as the thrown error. */
export function interpretGoal(
  goalId: string,
): Promise<InterpretationView> {
  return request<InterpretationView>(
    `/api/goals/${goalId}/assistant/interpretations`,
    { method: "POST" },
  );
}
