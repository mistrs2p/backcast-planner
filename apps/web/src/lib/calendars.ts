// Browser-side client for the calendar API (TASK-113).
//
// Types mirror packages/contracts/openapi.json (ADR-008). Requests
// go to /api/* on this origin and are proxied to the backend by
// next.config.ts rewrites.

/** CalendarResponse from the OpenAPI contract. */
export type CalendarView = {
  calendar_id: string;
  user_id: string;
  timezone: string;
  created_at: string;
  updated_at: string;
};

/** EventResponse from the OpenAPI contract. */
export type EventView = {
  event_id: string;
  calendar_id: string;
  title: string;
  start: string;
  end: string;
  description: string;
  created_at: string;
  updated_at: string;
};

/** ConflictResponse from the OpenAPI contract — an overlapping
 * event pair and the window they share. */
export type ConflictView = {
  first: EventView;
  second: EventView;
  start: string;
  end: string;
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

/** The user's calendar, or null while they own none. */
export async function getCalendarForUser(
  userId: string,
): Promise<CalendarView | null> {
  const response = await fetch(`/api/users/${userId}/calendar`, {
    headers: { Accept: "application/json" },
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as CalendarView;
}

/** Create the user's calendar (one per user in the MVP). */
export function createCalendar(draft: {
  user_id: string;
  timezone?: string;
}): Promise<CalendarView> {
  return request<CalendarView>("/api/calendars", {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

/** The calendar's events, earliest start first. */
export function listEvents(
  calendarId: string,
): Promise<EventView[]> {
  return request<EventView[]>(`/api/calendars/${calendarId}/events`);
}

/** Place an event on the calendar (normalized to UTC by the
 * backend — a missing zone is never guessed). */
export function addEvent(
  calendarId: string,
  draft: {
    title: string;
    start: string;
    end: string;
    description?: string;
  },
): Promise<EventView> {
  return request<EventView>(`/api/calendars/${calendarId}/events`, {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

/** The overlapping event pairs on the calendar. */
export function listConflicts(
  calendarId: string,
): Promise<ConflictView[]> {
  return request<ConflictView[]>(`/api/calendars/${calendarId}/conflicts`);
}
