import type { Metadata } from "next";

import { CalendarBoard } from "@/components/calendar-board";

export const metadata: Metadata = {
  title: "Calendar",
};

/**
 * The user's calendar (TASK-113): events placed in time and the
 * conflicts among them. Unlike the goal pages, the calendar is
 * user-scoped, not goal-scoped, so it hangs off the top-level
 * navigation; the board is a client component because the user id
 * is browser-held (the MVP's scoping convention).
 */
export default function CalendarPage() {
  return (
    <section aria-labelledby="calendar-heading">
      <h1 id="calendar-heading">Calendar</h1>
      <CalendarBoard />
    </section>
  );
}
