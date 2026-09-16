import { Card } from "@/components/ui/card";
import type { PlanVersionView } from "@/lib/replanning";

function formatHours(hours: number): string {
  if (hours === 0) {
    return "0h";
  }
  const rounded = Math.round(hours * 10) / 10;
  return `${rounded}h`;
}

function changes(version: PlanVersionView): string {
  const parts: string[] = [];
  if (version.revised_task_ids.length > 0) {
    parts.push(
      `revised ${version.revised_task_ids.length} ${
        version.revised_task_ids.length === 1 ? "task" : "tasks"
      }`,
    );
  }
  if (version.workload_hours !== null) {
    parts.push(`workload ${formatHours(version.workload_hours)}`);
  }
  if (version.title !== null) {
    parts.push(`retitled “${version.title}”`);
  }
  return parts.join(" · ");
}

/**
 * The plan's version history (TASK-115): every meaningful replan as
 * a traceable version — why the plan changed and what moved. Pure
 * display; a server component by default. The replans themselves
 * happen through the forms alongside (replan-forms.tsx).
 */
export function PlanVersionList({
  versions,
}: {
  versions: PlanVersionView[];
}) {
  return (
    <Card
      title="Plan history"
      actions={
        <span className="text-sm text-text-muted">
          {versions.length > 0
            ? `${versions.length} ${versions.length === 1 ? "version" : "versions"}`
            : undefined}
        </span>
      }
    >
      {versions.length > 0 ? (
        <ol className="flex flex-col gap-3">
          {versions.map((version) => (
            <li key={version.version_id} className="text-text">
              <span className="font-semibold">v{version.version}</span>{" "}
              <span className="text-text-muted">
                {new Date(version.created_at).toLocaleString()}
              </span>
              <p>{version.reason}</p>
              {changes(version) ? (
                <p className="text-sm text-text-muted">
                  {changes(version)}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-text-muted">
          No replans yet — the plan stands as published.
        </p>
      )}
    </Card>
  );
}
