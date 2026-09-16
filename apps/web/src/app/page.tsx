import type { Metadata } from "next";

import { GoalBoard } from "@/components/goal-board";

export const metadata: Metadata = {
  title: "Goals",
};

/**
 * The goals home — the MVP's single entry point (TASK-107). The
 * page is a server shell; the board (creation form plus the user's
 * goal list) is a client component because it talks to the API
 * under the browser's user-id convention.
 */
export default function GoalsPage() {
  return (
    <section aria-labelledby="goals-heading">
      <h1 id="goals-heading">Goals</h1>
      <p>
        Define where you want to be; the system works backwards to
        determine what must happen and what you can do now.
      </p>
      <GoalBoard />
    </section>
  );
}
