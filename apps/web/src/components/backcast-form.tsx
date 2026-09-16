"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TextField } from "@/components/ui/text-field";
import { defineBackcast } from "@/lib/backcast";

/**
 * The backcast definition form (TASK-109): pipeline steps 1–4 of
 * docs/04 — where you are, where you want to be by when, and (in a
 * sentence) the distance between the two. The domain enforces the
 * rules (non-empty narratives, a target date in the future); the
 * form mirrors them for immediate feedback and surfaces the
 * server's message for anything past it. One backcast per goal in
 * the MVP — redefining arrives with replanning.
 */
export function BackcastForm({ goalId }: { goalId: string }) {
  const router = useRouter();
  const [currentNarrative, setCurrentNarrative] = useState("");
  const [futureDescription, setFutureDescription] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [gapNarrative, setGapNarrative] = useState("");
  const [currentError, setCurrentError] = useState<string>();
  const [futureError, setFutureError] = useState<string>();
  const [dateError, setDateError] = useState<string>();
  const [formError, setFormError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const current = currentNarrative.trim();
    const future = futureDescription.trim();
    const date = targetDate.trim();
    setCurrentError(current ? undefined : "Describe where you are today.");
    setFutureError(future ? undefined : "Describe the destination.");
    setDateError(date ? undefined : "Pick a target date.");
    if (!current || !future || !date) {
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
      await defineBackcast(goalId, {
        current_narrative: current,
        future_description: future,
        target_date: target.toISOString(),
        gap_narrative: gapNarrative.trim(),
      });
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
    <Card title="Define the backcast">
      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <TextField
          label="Where are you now?"
          name="current_narrative"
          value={currentNarrative}
          onChange={(event) => setCurrentNarrative(event.target.value)}
          required
          hint="An honest snapshot of today's reality."
          error={currentError}
        />
        <TextField
          label="Where do you want to be?"
          name="future_description"
          value={futureDescription}
          onChange={(event) => setFutureDescription(event.target.value)}
          required
          hint="The destination, stated as an observable state."
          error={futureError}
        />
        <TextField
          label="By when?"
          name="target_date"
          type="date"
          value={targetDate}
          onChange={(event) => setTargetDate(event.target.value)}
          required
          error={dateError}
        />
        <TextField
          label="The gap, in a sentence"
          name="gap_narrative"
          value={gapNarrative}
          onChange={(event) => setGapNarrative(event.target.value)}
          hint="Optional — what stands between the two?"
        />
        {formError ? (
          <p className="field__error" role="alert">
            {formError}
          </p>
        ) : null}
        <div>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Calculating…" : "Calculate the backcast"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
