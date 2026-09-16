import { Card } from "@/components/ui/card";
import type { BackcastView } from "@/lib/backcast";

function formatDate(moment: string): string {
  return new Date(moment).toLocaleDateString();
}

/**
 * The backcast visualization (TASK-109): the intent layer of one
 * goal rendered as the chain it is — where you are, the recorded
 * distance, and the destination the plan will be built backward
 * from (docs/04, steps 1–4). Pure display; a server component by
 * default.
 */
export function BackcastChain({ backcast }: { backcast: BackcastView }) {
  return (
    <div className="flex flex-col gap-6" aria-label="Backcast">
      <Card title="Now">
        <p className="text-text">{backcast.current.narrative}</p>
        <p className="mt-2 text-sm text-text-muted">
          Captured {formatDate(backcast.current.captured_at)}
        </p>
      </Card>
      <Card title="The gap">
        {backcast.gap.narrative ? (
          <p className="text-text">{backcast.gap.narrative}</p>
        ) : (
          <p className="text-text-muted">No gap narrative recorded.</p>
        )}
        {backcast.gap.dimensions.length > 0 ? (
          <ul className="mt-2 flex flex-col gap-2">
            {backcast.gap.dimensions.map((dimension) => (
              <li
                key={dimension.metric_name}
                className="rounded-md bg-surface-muted p-3 text-sm"
              >
                <span className="font-semibold text-text">
                  {dimension.metric_name}:
                </span>{" "}
                <span className="text-text">
                  {String(dimension.current_value)}
                </span>{" "}
                → {String(dimension.target_value)}
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
      <Card title="Destination">
        <p className="text-text">{backcast.future.description}</p>
        <p className="mt-2 text-sm text-text-muted">
          Target {formatDate(backcast.future.target_date)}
        </p>
      </Card>
    </div>
  );
}
