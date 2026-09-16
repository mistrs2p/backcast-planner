"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TextField } from "@/components/ui/text-field";
import { createGoal, listGoals, type Goal } from "@/lib/goals";
import { browserUserId } from "@/lib/user";

// The MVP's identity convention: user id is browser-held.
const MAX_TITLE_LENGTH = 200;

type LoadState =
  | { phase: "loading" }
  | { phase: "ready"; goals: Goal[] }
  | { phase: "failed"; message: string };

/**
 * The goals home: the creation form and the user's goal list
 * (TASK-107). The domain owns the rules — non-blank stripped title
 * ≤ 200 chars, description ≤ 2000 — and the backend enforces them;
 * the form mirrors the title rule for immediate feedback and shows
 * the server's message for anything that slips past.
 */
export function GoalBoard() {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [titleError, setTitleError] = useState<string>();
  const [formError, setFormError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const [load, setLoad] = useState<LoadState>({ phase: "loading" });

  const refresh = useCallback(async () => {
    setLoad({ phase: "loading" });
    try {
      const goals = await listGoals(browserUserId());
      setLoad({ phase: "ready", goals });
    } catch (error) {
      setLoad({
        phase: "failed",
        message: error instanceof Error ? error.message : "unknown error",
      });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) {
      setTitleError("Title is required.");
      return;
    }
    if (trimmed.length > MAX_TITLE_LENGTH) {
      setTitleError(`Title must be at most ${MAX_TITLE_LENGTH} characters.`);
      return;
    }
    setTitleError(undefined);
    setFormError(undefined);
    setSubmitting(true);
    try {
      await createGoal({
        user_id: browserUserId(),
        title: trimmed,
        description: description.trim(),
      });
      setTitle("");
      setDescription("");
      await refresh();
    } catch (error) {
      setFormError(
        error instanceof Error ? error.message : "unknown error",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card title="New goal">
        <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
          <TextField
            label="Title"
            name="title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            maxLength={MAX_TITLE_LENGTH + 1}
            error={titleError}
          />
          <TextField
            label="Description"
            name="description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            hint="Optional — what does done look like?"
          />
          {formError ? (
            <p className="field__error" role="alert">
              {formError}
            </p>
          ) : null}
          <div>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Creating…" : "Create goal"}
            </Button>
          </div>
        </form>
      </Card>

      <Card title="Your goals">
        {load.phase === "loading" ? <p>Loading…</p> : null}
        {load.phase === "failed" ? (
          <p className="field__error" role="alert">
            Could not load goals: {load.message}
          </p>
        ) : null}
        {load.phase === "ready" ? (
          load.goals.length === 0 ? (
            <p>No goals yet — create your first above.</p>
          ) : (
            <ul className="flex flex-col gap-4">
              {load.goals.map((goal) => (
                <li key={goal.goal_id} className="rounded-md bg-surface-muted p-4">
                  <p className="font-semibold text-text">{goal.title}</p>
                  {goal.description ? (
                    <p className="text-text-muted">{goal.description}</p>
                  ) : null}
                  <p className="text-sm text-text-muted">
                    {goal.status} · created{" "}
                    {new Date(goal.created_at).toLocaleDateString()}
                  </p>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </Card>
    </div>
  );
}
