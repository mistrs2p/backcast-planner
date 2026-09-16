"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TextField } from "@/components/ui/text-field";
import { defineMilestone } from "@/lib/milestones";

/**
 * The add-checkpoint form (TASK-110): one measurable step with a
 * target date on the goal's backcasting run. The domain enforces
 * the rules (non-empty title, a target date in the future, a
 * running run); the form mirrors them and surfaces the server's
 * message for anything past it.
 */
export function MilestoneForm({ goalId }: { goalId: string }) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [description, setDescription] = useState("");
  const [titleError, setTitleError] = useState<string>();
  const [dateError, setDateError] = useState<string>();
  const [formError, setFormError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedTitle = title.trim();
    const date = targetDate.trim();
    setTitleError(trimmedTitle ? undefined : "Title is required.");
    setDateError(date ? undefined : "Pick a target date.");
    if (!trimmedTitle || !date) {
      return;
    }
    const target = new Date(`${date}T00:00:00Z`);
    if (Number.isNaN(target.getTime()) || target.getTime() <= Date.now()) {
      setDateError("The target date must be in the future.");
      return;
    }
    setFormError(undefined);
    setSubmitting(true);
    try {
      await defineMilestone(goalId, {
        title: trimmedTitle,
        target_date: target.toISOString(),
        description: description.trim(),
      });
      setTitle("");
      setTargetDate("");
      setDescription("");
      router.refresh();
    } catch (error) {
      setFormError(
        error instanceof Error ? error.message : "unknown error",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card title="Add a milestone">
      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <TextField
          label="Title"
          name="milestone-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          required
          hint="A measurable checkpoint."
          error={titleError}
        />
        <TextField
          label="Target date"
          name="milestone-target"
          type="date"
          value={targetDate}
          onChange={(event) => setTargetDate(event.target.value)}
          required
          error={dateError}
        />
        <TextField
          label="Description"
          name="milestone-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          hint="Optional — what does reaching it prove?"
        />
        {formError ? (
          <p className="field__error" role="alert">
            {formError}
          </p>
        ) : null}
        <div>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Adding…" : "Add milestone"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
