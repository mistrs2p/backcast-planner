"use client";

import { useState } from "react";

import { ErrorLine, usePlanAction } from "@/components/plan-forms";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import type { TaskView } from "@/lib/plans";
import { reviseTask } from "@/lib/plans";

/** Format an ISO instant for a datetime-local input (local time). */
function toLocalInput(iso: string): string {
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * The task revision form (TASK-112): assembly-time editing of one
 * task on the DRAFT plan — fix a title, land a missing estimate,
 * set or move a deadline. Collapsed by default; the domain keeps
 * the rules (omitted fields keep their value, publishing still
 * needs every task estimated) and the form surfaces its refusals.
 */
export function TaskEditForm({
  goalId,
  task,
}: {
  goalId: string;
  task: TaskView;
}) {
  const { error, busy, run } = usePlanAction(goalId);
  const [title, setTitle] = useState(task.title);
  const [duration, setDuration] = useState(
    task.duration_hours !== null ? String(task.duration_hours) : "",
  );
  const [deadline, setDeadline] = useState(
    task.deadline ? toLocalInput(task.deadline) : "",
  );
  const [description, setDescription] = useState(task.description);

  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-sm text-text-muted">
        Edit task
      </summary>
      <form
        className="mt-3 flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          const trimmed = title.trim();
          const hours = duration.trim() ? Number(duration) : undefined;
          if (!trimmed || hours !== undefined && !(hours > 0)) {
            return;
          }
          void run(() =>
            reviseTask(goalId, task.task_id, {
              title: trimmed,
              description: description.trim(),
              duration_hours: hours,
              deadline: deadline
                ? new Date(deadline).toISOString()
                : undefined,
            }),
          );
        }}
      >
        <TextField
          label="Title"
          name={`task-title-${task.task_id}`}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          required
        />
        <TextField
          label="Estimate (hours)"
          name={`task-duration-${task.task_id}`}
          type="number"
          min="0.5"
          step="0.5"
          value={duration}
          onChange={(event) => setDuration(event.target.value)}
          hint="Empty keeps the current estimate."
        />
        <TextField
          label="Deadline"
          name={`task-deadline-${task.task_id}`}
          type="datetime-local"
          value={deadline}
          onChange={(event) => setDeadline(event.target.value)}
        />
        <TextField
          label="Description"
          name={`task-description-${task.task_id}`}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          hint="Optional."
        />
        <ErrorLine error={error} />
        <div>
          <Button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save revision"}
          </Button>
        </div>
      </form>
    </details>
  );
}
