// Server-side access to the backend API (TASK-108).
//
// Next rewrites /api/* only for incoming browser requests; a server
// component fetching during render must call the backend directly,
// so the same API_ORIGIN knob from next.config.ts resolves the
// absolute origin here.

export function apiOrigin(): string {
  return process.env.API_ORIGIN ?? "http://localhost:8000";
}

/** GET a JSON resource from the backend, or null when absent. */
export async function serverGet<T>(path: string): Promise<T | null> {
  let response: Response;
  try {
    response = await fetch(`${apiOrigin()}${path}`);
  } catch {
    // Backend unreachable — render the error state, not a crash.
    throw new Error("The planning service is unreachable.");
  }
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`The planning service returned ${response.status}.`);
  }
  return (await response.json()) as T;
}
