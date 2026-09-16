import { Card } from "@/components/ui/card";
import type { MilestoneView } from "@/lib/milestones";

function formatDate(moment: string): string {
  return new Date(moment).toLocaleDateString();
}

/**
 * The goal's checkpoints on its backcasting run (TASK-110),
 * earliest target first — the path from now to the destination,
 * walkable as a list. Pure display; a server component by default.
 */
export function MilestoneList({ milestones }: { milestones: MilestoneView[] }) {
  return (
    <Card title="Milestones">
      {milestones.length === 0 ? (
        <p className="text-text-muted">
          No checkpoints yet — pin the measurable steps between here
          and the destination.
        </p>
      ) : (
        <ol className="flex flex-col gap-4">
          {milestones.map((milestone, index) => (
            <li
              key={milestone.milestone_id}
              className="rounded-md bg-surface-muted p-4"
            >
              <p className="font-semibold text-text">
                {index + 1}. {milestone.title}
              </p>
              {milestone.description ? (
                <p className="text-text-muted">{milestone.description}</p>
              ) : null}
              <p className="text-sm text-text-muted">
                Target {formatDate(milestone.target_date)}
              </p>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
