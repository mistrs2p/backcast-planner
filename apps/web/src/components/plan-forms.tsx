"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TextField } from "@/components/ui/text-field";
import type { OutcomeView } from "@/lib/plans";
import { addOutcome, addTask, beginPlan, publishPlan } from "@/lib/plans";

/**
 * The plan's assembly controls (TASK-111), shown while the plan is
 * a DRAFT: begin it from the finished backcast, define outcomes,
 * add tasks, and publish with the computed workload. The domain
 * holds the rules (publishing needs at least one estimated task);
 * these forms surface the server's message when it refuses.
 */

function usePlanAction(goalId: string) {
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

export function BeginPlanForm({ goalId }: { goalId: string }) {
  const { error, busy, run } = usePlanAction(goalId);
  const [title, setTitle] = useState("");

  return (
    <Card title="Plan">
      <p className="text-text-muted">
        The backcast is defined. Begin the plan to execute it — the
        run closes and a draft plan opens from its results.
      </p>
      <form
        className="mt-4 flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void run(() => beginPlan(goalId, title.trim()));
        }}
      >
        <TextField
          label="Plan title"
          name="plan-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          hint="Optional — defaults to the goal's name."
        />
        <ErrorLine error={error} />
        <div>
          <Button type="submit" disabled={busy}>
            {busy ? "Beginning…" : "Begin the plan"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function AddOutcomeForm({ goalId }: { goalId: string }) {
  const { error, busy, run } = usePlanAction(goalId);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  return (
    <Card title="Add an outcome">
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          const trimmed = title.trim();
          if (!trimmed) {
            return;
          }
          void run(() =>
            addOutcome(goalId, {
              title: trimmed,
              description: description.trim(),
            }),
          ).then(() => {
            setTitle("");
            setDescription("");
          });
        }}
      >
        <TextField
          label="Title"
          name="outcome-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          required
          hint="A result the plan commits to producing."
        />
        <TextField
          label="Description"
          name="outcome-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          hint="Optional — what does achieving it look like?"
        />
        <ErrorLine error={error} />
        <div>
          <Button type="submit" disabled={busy}>
            {busy ? "Adding…" : "Add outcome"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function AddTaskForm({
  goalId,
  outcomes,
}: {
  goalId: string;
  outcomes: OutcomeView[];
}) {
  const { error, busy, run } = usePlanAction(goalId);
  const [title, setTitle] = useState("");
  const [duration, setDuration] = useState("");
  const [description, setDescription] = useState("");
  const [serving, setServing] = useState<Record<string, boolean>>({});

  const selectedOutcomes = Object.entries(serving)
    .filter(([, checked]) => checked)
    .map(([id]) => id);

  return (
    <Card title="Add a task">
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          const trimmed = title.trim();
          const hours = duration.trim() ? Number(duration) : undefined;
          if (!trimmed || hours !== undefined && !(hours > 0)) {
            return;
          }
          void run(() =>
            addTask(goalId, {
              title: trimmed,
              description: description.trim(),
              duration_hours: hours,
              outcome_ids: selectedOutcomes,
            }),
          ).then(() => {
            setTitle("");
            setDuration("");
            setDescription("");
            setServing({});
          });
        }}
      >
        <TextField
          label="Title"
          name="task-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          required
          hint="One actionable unit of work."
        />
        <TextField
          label="Estimate (hours)"
          name="task-duration"
          type="number"
          min="0.5"
          step="0.5"
          value={duration}
          onChange={(event) => setDuration(event.target.value)}
          hint="Required before the plan can publish."
        />
        <TextField
          label="Description"
          name="task-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          hint="Optional."
        />
        {outcomes.length > 0 ? (
          <fieldset className="flex flex-col gap-2">
            <legend className="field__label">Serves outcomes</legend>
            {outcomes.map((outcome) => (
              <label
                key={outcome.outcome_id}
                className="flex items-center gap-2 text-sm text-text"
              >
                <input
                  type="checkbox"
                  checked={serving[outcome.outcome_id] ?? false}
                  onChange={(event) =>
                    setServing((previous) => ({
                      ...previous,
                      [outcome.outcome_id]: event.target.checked,
                    }))
                  }
                />
                {outcome.title}
              </label>
            ))}
          </fieldset>
        ) : null}
        <ErrorLine error={error} />
        <div>
          <Button type="submit" disabled={busy}>
            {busy ? "Adding…" : "Add task"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function PublishPlanButton({
  goalId,
  disabled,
}: {
  goalId: string;
  disabled: boolean;
}) {
  const { error, busy, run } = usePlanAction(goalId);
  return (
    <div className="flex flex-col gap-2">
      <Button
        variant="secondary"
        disabled={disabled || busy}
        onClick={() => void run(() => publishPlan(goalId))}
      >
        {busy ? "Publishing…" : "Publish the plan"}
      </Button>
      <ErrorLine error={error} />
      {disabled ? (
        <p className="text-sm text-text-muted">
          Publishing needs at least one task with an estimate.
        </p>
      ) : null}
    </div>
  );
}
