import { Card } from "@/components/ui/card";
import type { ProgressView } from "@/lib/progress";

function formatHours(hours: number): string {
  if (hours === 0) {
    return "0h";
  }
  const rounded = Math.round(hours * 10) / 10;
  return `${rounded}h`;
}

function formatPercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

/**
 * The progress view (TASK-114): one snapshot of the
 * planned-actual-progress triad (docs/07) — work actually done
 * against work planned, and how many tasks are complete. Pure
 * display; a server component by default. Recording work and
 * taking the next snapshot happen through the forms alongside
 * (progress-forms.tsx).
 */
export function ProgressView({ progress }: { progress: ProgressView }) {
  return (
    <Card
      title="Progress"
      actions={
        <span className="text-sm text-text-muted">
          taken {new Date(progress.taken_at).toLocaleString()}
        </span>
      }
    >
      <div className="flex flex-col gap-2">
        <p className="text-text">
          <span className="font-semibold">
            {formatHours(progress.actual_hours)}
          </span>{" "}
          of {formatHours(progress.planned_hours)} planned ·{" "}
          {formatHours(progress.remaining_hours)} remaining
        </p>
        <p className="text-text">
          {progress.completed_task_count} of {progress.task_count} tasks
          complete · {formatPercent(progress.progress)} of the work ·{" "}
          {formatPercent(progress.completion_rate)} completion rate
        </p>
      </div>
    </Card>
  );
}
