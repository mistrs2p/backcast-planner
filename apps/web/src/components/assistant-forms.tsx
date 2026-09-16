"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { interpretGoal } from "@/lib/assistant";

/**
 * The assistant's ask form (TASK-116): one button — read the goal
 * against its current state. The domain keeps the rules and the
 * server keeps the honesty (a server without an LLM wired says so,
 * a vendor fault surfaces), and this form shows the message either
 * way. Proposals are recorded verbatim with provenance; nothing
 * here interprets them (ADR-002).
 */
export function InterpretGoalButton({ goalId }: { goalId: string }) {
  const router = useRouter();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run() {
    setError(undefined);
    setBusy(true);
    try {
      await interpretGoal(goalId);
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "unknown error",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Button
        variant="secondary"
        disabled={busy}
        onClick={() => void run()}
      >
        {busy ? "Reading the goal…" : "Interpret this goal"}
      </Button>
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
      <p className="text-sm text-text-muted">
        The assistant reads the goal against its current state and
        proposes an interpretation — the system validates, the LLM
        proposes.
      </p>
    </div>
  );
}
