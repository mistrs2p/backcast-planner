import { Card } from "@/components/ui/card";
import type { InterpretationView } from "@/lib/assistant";

/**
 * The assistant's reading history (TASK-116): every AI proposal
 * that read the goal, verbatim, with the provider and model that
 * actually answered (ADR-002 — the LLM proposes, the domain
 * validates). Pure display; a server component by default. Asking
 * for the next reading happens through the button alongside
 * (assistant-forms.tsx).
 */
export function AssistantCard({
  interpretations,
}: {
  interpretations: InterpretationView[];
}) {
  return (
    <Card
      title="AI assistant"
      actions={
        <span className="text-sm text-text-muted">
          {interpretations.length > 0
            ? `${interpretations.length} ${
                interpretations.length === 1 ? "reading" : "readings"
              }`
            : undefined}
        </span>
      }
    >
      {interpretations.length > 0 ? (
        <ul className="flex flex-col gap-4">
          {interpretations.map((record) => (
            <li key={record.interpretation_id} className="text-text">
              <p>{record.proposal}</p>
              <p className="mt-1 text-sm text-text-muted">
                {record.provider} · {record.model} ·{" "}
                {new Date(record.created_at).toLocaleString()}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-text-muted">
          No readings yet — ask the assistant to interpret this goal
          against its current state.
        </p>
      )}
    </Card>
  );
}
