"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TextField } from "@/components/ui/text-field";
import type { TaskView } from "@/lib/plans";
import { recordExecution, takeSnapshot } from "@/lib/progress";

/**
 * The progress forms (TASK-114): record a sitting of actual work on
 * one of the plan's tasks, and take the next snapshot once it ends.
 * The domain holds the rules — only ended work counts, unknown
 * workload means no derivable progress — and these forms surface the
 * server's message when it refuses.
 */

function useProgressAction(goalId: string) {
  const router = useRouter();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>) {
    setError(undefined);
    setBusy(true);
    try {
      await action();
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "unknown error",
      );
    } finally {
      setBusy(false);
    }
  }

  return { error, busy, run };
}

function ErrorLine({ error }: { error?: string }) {
  if (!error) {
    return null;
  }
  return (
    <p className="field__error" role="alert">
      {error}
    </p>
  );
}

export function RecordWorkForm({
  goalId,
  tasks,
}: {
  goalId: string;
  tasks: TaskView[];
}) {
  const { error, busy, run } = useProgressAction(goalId);
  const [taskId, setTaskId] = useState(tasks[0]?.task_id ?? "");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  return (
    <Card title="Record work">
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!taskId || !start || !end) {
            return;
          }
          void run(() =>
            recordExecution(goalId, {
              task_id: taskId,
              start: new Date(start).toISOString(),
              end: new Date(end).toISOString(),
            }),
          ).then(() => {
            setStart("");
            setEnd("");
          });
        }}
      >
        <div className="flex flex-col gap-2">
          <label
            htmlFor="work-task"
            className="field__label text-sm font-semibold text-text-muted"
          >
            Task
          </label>
          <select
            id="work-task"
            name="work-task"
            className="field__input"
            value={taskId}
            onChange={(event) => setTaskId(event.target.value)}
            required
          >
            {tasks.map((task) => (
              <option key={task.task_id} value={task.task_id}>
                {task.title}
              </option>
            ))}
          </select>
        </div>
        <TextField
          label="Started"
          name="work-start"
          type="datetime-local"
          value={start}
          onChange={(event) => setStart(event.target.value)}
          required
        />
        <TextField
          label="Ended"
          name="work-end"
          type="datetime-local"
          value={end}
          onChange={(event) => setEnd(event.target.value)}
          required
          hint="Work counts once it has ended — a sitting in progress is not actual yet."
        />
        <ErrorLine error={error} />
        <div>
          <Button type="submit" disabled={busy}>
            {busy ? "Recording…" : "Record work"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function TakeSnapshotButton({ goalId }: { goalId: string }) {
  const { error, busy, run } = useProgressAction(goalId);
  return (
    <div className="flex flex-col gap-2">
      <Button
        variant="secondary"
        disabled={busy}
        onClick={() => void run(() => takeSnapshot(goalId))}
      >
        {busy ? "Taking…" : "Take a progress snapshot"}
      </Button>
      <ErrorLine error={error} />
      <p className="text-sm text-text-muted">
        A snapshot reads the plan&apos;s progress at this moment and is
        kept as history.
      </p>
    </div>
  );
}
