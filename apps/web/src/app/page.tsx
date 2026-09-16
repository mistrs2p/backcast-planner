import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Goals",
};

/**
 * The goals home — the MVP's single entry point. Goal creation
 * arrives with TASK-107 and the list with the API wiring; the
 * shell provides the frame they land in.
 */
export default function GoalsPage() {
  return (
    <section aria-labelledby="goals-heading">
      <h1 id="goals-heading">Goals</h1>
      <p>
        Define where you want to be; the system works backwards to
        determine what must happen and what you can do now.
      </p>
      <p>Goal creation arrives with the next milestone.</p>
    </section>
  );
}
