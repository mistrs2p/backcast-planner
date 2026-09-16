// Browser identity convention (TASK-107).
//
// The MVP has no authentication: the API takes a client-supplied
// user id (the same convention the calendars API established), so
// this browser keeps a UUID in localStorage. It is a convention for
// scoping data to one browser profile, not a security boundary —
// production auth arrives with EPIC-012 and will replace it.
//
// localStorage can be unavailable or throw (private mode, blocked
// site data); in that case we degrade to a per-page-load id so the
// app still works, just without cross-visit continuity.

const STORAGE_KEY = "backcast.userId";

/** Fallback id when storage is unavailable — one per page load, so
 * a single visit is never split across two users. */
let cached: string | undefined;

function randomUserId(): string {
  return crypto.randomUUID();
}

/** The stable browser user id, creating and persisting it on first
 * use; a session-scoped fallback when storage is unavailable. */
export function browserUserId(): string {
  try {
    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing) {
      return existing;
    }
    const created = randomUserId();
    window.localStorage.setItem(STORAGE_KEY, created);
    return created;
  } catch {
    cached ??= randomUserId();
    return cached;
  }
}
