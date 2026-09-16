"use client";

import { useState } from "react";

import { ErrorLine, usePlanAction } from "@/components/plan-forms";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import type { TaskView } from "@/lib/plans";
import { replanPlanGlobally, replanTaskLocally } from "@/lib/replanning";

/** Format an ISO instant for a datetime-local input (local time). */
function toLocalInput(iso: string): string {
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * The replanning forms (TASK-115): docs/08's level 2 driven by hand,
 * on a plan past assembly. The local form re-estimates or
 * re-commits one task in place; the global form re-derives the whole
 * plan. Both demand a reason — a replan without a why is not
 * traceable — and both produce a plan version the history shows.
 * The domain holds the rules (a revision that changes nothing is
 * refused; a global replan faces every task's estimate) and these
 * forms surface its message when it refuses.
 */
export function LocalReplanForm({
  goalId,
  task,
}: {
  goalId: string;
  task: TaskView;
}) {
  const { error, busy, run } = usePlanAction(goalId);
  const [reason, setReason] = useState("");
  const [duration, setDuration] = useState(
    task.duration_hours !== null ? String(task.duration_hours) : "",
  );
  const [deadline, setDeadline] = useState(
    task.deadline ? toLocalInput(task.deadline) : "",
  );

  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-sm text-text-muted">
        Replan this task
      </summary>
      <form
        className="mt-3 flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          const why = reason.trim();
          const hours = duration.trim() ? Number(duration) : undefined;
          if (!why || (hours !== undefined && !(hours > 0))) {
            return;
          }
          void run(() =>
            replanTaskLocally(goalId, {
              task_id: task.task_id,
              reason: why,
              duration_hours: hours,
              deadline: deadline
                ? new Date(deadline).toISOString()
                : undefined,
            }),
          ).then(() => {
            setReason("");
          });
        }}
      >
        <TextField
          label="Why is the plan changing?"
          name={`replan-reason-${task.task_id}`}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          required
          hint="The version trail records this reason."
        />
        <TextField
          label="New estimate (hours)"
          name={`replan-duration-${task.task_id}`}
          type="number"
          min="0.5"
          step="0.5"
          value={duration}
          onChange={(event) => setDuration(event.target.value)}
          hint="Empty keeps the current estimate — a local replan shifts the plan's workload by the change."
        />
        <TextField
          label="New deadline"
          name={`replan-deadline-${task.task_id}`}
          type="datetime-local"
          value={deadline}
          onChange={(event) => setDeadline(event.target.value)}
        />
        <ErrorLine error={error} />
        <div>
          <Button type="submit" disabled={busy}>
            {busy ? "Replanning…" : "Replan task"}
          </Button>
        </div>
      </form>
    </details>
  );
}

export function GlobalReplanForm({ goalId }: { goalId: string }) {
  const { error, busy, run } = usePlanAction(goalId);
  const [reason, setReason] = useState("");
  const [title, setTitle] = useState("");

  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-sm text-text-muted">
        Re-derive the whole plan
      </summary>
      <form
        className="mt-3 flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          const why = reason.trim();
          if (!why) {
            return;
          }
          void run(() =>
            replanPlanGlobally(goalId, {
              reason: why,
              title: title.trim() || undefined,
            }),
          ).then(() => {
            setReason("");
            setTitle("");
          });
        }}
      >
        <TextField
          label="Why is the plan changing?"
          name="replan-global-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          required
          hint="The version trail records this reason."
        />
        <TextField
          label="New title"
          name="replan-global-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          hint="Optional — empty keeps the plan's title."
        />
        <p className="text-sm text-text-muted">
          A global replan recomputes the workload from every task&apos;s
          estimate — there is nothing left to preserve.
        </p>
        <ErrorLine error={error} />
        <div>
          <Button type="submit" disabled={busy}>
            {busy ? "Re-deriving…" : "Re-derive plan"}
          </Button>
        </div>
      </form>
    </details>
  );
}
