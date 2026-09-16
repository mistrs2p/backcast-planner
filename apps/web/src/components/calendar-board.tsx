"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TextField } from "@/components/ui/text-field";
import {
  addEvent,
  createCalendar,
  getCalendarForUser,
  listConflicts,
  listEvents,
  type CalendarView,
  type ConflictView,
  type EventView,
} from "@/lib/calendars";
import { browserUserId } from "@/lib/user";

type BoardState =
  | { phase: "loading" }
  | { phase: "no-calendar" }
  | {
      phase: "ready";
      calendar: CalendarView;
      events: EventView[];
      conflicts: ConflictView[];
    }
  | { phase: "failed"; message: string };

function formatRange(start: string, end: string): string {
  const from = new Date(start);
  const to = new Date(end);
  const day = from.toLocaleDateString();
  const sameDay = to.toLocaleDateString() === day;
  return sameDay
    ? `${day} ${from.toLocaleTimeString()} – ${to.toLocaleTimeString()}`
    : `${from.toLocaleString()} – ${to.toLocaleString()}`;
}

/**
 * The calendar board (TASK-113): the user's calendar, its events
 * (earliest first), and the conflicts among them. The user id is
 * browser-held (the MVP's scoping convention), so the board is a
 * client component like the goal board; the domain holds the rules
 * — one calendar per user, aware datetimes only, end after start —
 * and the forms surface the server's refusals.
 */
export function CalendarBoard() {
  const [state, setState] = useState<BoardState>({ phase: "loading" });

  const refresh = useCallback(async () => {
    setState({ phase: "loading" });
    try {
      const calendar = await getCalendarForUser(browserUserId());
      if (calendar === null) {
        setState({ phase: "no-calendar" });
        return;
      }
      const [events, conflicts] = await Promise.all([
        listEvents(calendar.calendar_id),
        listConflicts(calendar.calendar_id),
      ]);
      setState({
        phase: "ready",
        calendar,
        events,
        conflicts,
      });
    } catch (caught) {
      setState({
        phase: "failed",
        message: caught instanceof Error ? caught.message : "unknown error",
      });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="flex flex-col gap-6">
      {state.phase === "loading" ? <p>Loading…</p> : null}
      {state.phase === "failed" ? (
        <p className="field__error" role="alert">
          Could not load the calendar: {state.message}
        </p>
      ) : null}
      {state.phase === "no-calendar" ? (
        <CreateCalendarCard onCreated={refresh} />
      ) : null}
      {state.phase === "ready" ? (
        <>
          <EventListCard
            events={state.events}
            timezone={state.calendar.timezone}
          />
          {state.conflicts.length > 0 ? (
            <ConflictCard conflicts={state.conflicts} />
          ) : null}
          <AddEventCard
            calendarId={state.calendar.calendar_id}
            onAdded={refresh}
          />
        </>
      ) : null}
    </div>
  );
}

function CreateCalendarCard({ onCreated }: { onCreated: () => void }) {
  const [timezone, setTimezone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  return (
    <Card title="Your calendar">
      <p className="text-text-muted">
        You do not have a calendar yet — create one to place events on
        it (one per user).
      </p>
      <form
        className="mt-4 flex flex-col gap-4"
        onSubmit={async (event) => {
          event.preventDefault();
          setError(undefined);
          setBusy(true);
          try {
            await createCalendar({
              user_id: browserUserId(),
              timezone: timezone.trim() || undefined,
            });
            onCreated();
          } catch (caught) {
            setError(
              caught instanceof Error ? caught.message : "unknown error",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        <TextField
          label="Timezone"
          name="calendar-timezone"
          value={timezone}
          onChange={(event) => setTimezone(event.target.value)}
          hint="Optional IANA name (e.g. Asia/Tehran) — defaults to UTC."
        />
        {error ? (
          <p className="field__error" role="alert">
            {error}
          </p>
        ) : null}
        <div>
          <Button type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create calendar"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function EventListCard({
  events,
  timezone,
}: {
  events: EventView[];
  timezone: string;
}) {
  return (
    <Card
      title="Events"
      actions={<span className="text-sm text-text-muted">{timezone}</span>}
    >
      {events.length === 0 ? (
        <p className="text-text-muted">
          No events yet — the calendar is where time is committed.
        </p>
      ) : (
        <ol className="flex flex-col gap-2">
          {events.map((event) => (
            <li
              key={event.event_id}
              className="rounded-md bg-surface-muted p-3"
            >
              <span className="font-semibold text-text">{event.title}</span>
              <span className="text-text-muted">
                {" "}
                · {formatRange(event.start, event.end)}
              </span>
              {event.description ? (
                <p className="text-sm text-text-muted">{event.description}</p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function ConflictCard({ conflicts }: { conflicts: ConflictView[] }) {
  return (
    <Card title="Conflicts">
      <ul className="flex flex-col gap-2">
        {conflicts.map((conflict, index) => (
          <li key={index} className="text-text" role="alert">
            “{conflict.first.title}” overlaps “{conflict.second.title}” (
            {formatRange(conflict.start, conflict.end)})
          </li>
        ))}
      </ul>
    </Card>
  );
}

function AddEventCard({
  calendarId,
  onAdded,
}: {
  calendarId: string;
  onAdded: () => void;
}) {
  const [title, setTitle] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  return (
    <Card title="Add an event">
      <form
        className="flex flex-col gap-4"
        onSubmit={async (event) => {
          event.preventDefault();
          const trimmed = title.trim();
          if (!trimmed || !start || !end) {
            return;
          }
          setError(undefined);
          setBusy(true);
          try {
            await addEvent(calendarId, {
              title: trimmed,
              start: new Date(start).toISOString(),
              end: new Date(end).toISOString(),
              description: description.trim(),
            });
            setTitle("");
            setStart("");
            setEnd("");
            setDescription("");
            onAdded();
          } catch (caught) {
            setError(
              caught instanceof Error ? caught.message : "unknown error",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        <TextField
          label="Title"
          name="event-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          required
        />
        <TextField
          label="Starts"
          name="event-start"
          type="datetime-local"
          value={start}
          onChange={(event) => setStart(event.target.value)}
          required
        />
        <TextField
          label="Ends"
          name="event-end"
          type="datetime-local"
          value={end}
          onChange={(event) => setEnd(event.target.value)}
          required
          hint="Must be after the start."
        />
        <TextField
          label="Description"
          name="event-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          hint="Optional."
        />
        {error ? (
          <p className="field__error" role="alert">
            {error}
          </p>
        ) : null}
        <div>
          <Button type="submit" disabled={busy}>
            {busy ? "Adding…" : "Add event"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
