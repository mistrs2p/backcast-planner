import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import type { PlanBundleView, TaskView } from "@/lib/plans";

function formatHours(hours: number): string {
  if (hours === 0) {
    return "0h";
  }
  const rounded = Math.round(hours * 10) / 10;
  return `${rounded}h`;
}

function formatDate(moment: string): string {
  return new Date(moment).toLocaleDateString();
}

/**
 * The plan view (TASK-111): what must happen and the workload it
 * requires — outcomes the plan commits to, tasks that execute
 * them, and the computed workload once published. Pure display; a
 * server component by default. Assembly forms render alongside
 * while the plan is still a DRAFT (see plan-forms.tsx), and
 * ``taskEdit`` (TASK-112) lets the page attach a revision form to
 * each task row for the same reason.
 */
export function PlanView({
  bundle,
  taskEdit,
}: {
  bundle: PlanBundleView;
  taskEdit?: (task: TaskView) => ReactNode;
}) {
  const { plan, outcomes, tasks } = bundle;
  return (
    <Card
      title={plan.title || "Plan"}
      actions={
        <span className="text-sm text-text-muted">
          {plan.status} · {formatHours(plan.workload_hours)} of work
        </span>
      }
    >
      <div className="flex flex-col gap-6">
        {outcomes.length > 0 ? (
          <div>
            <h3 className="font-semibold text-text">Outcomes</h3>
            <ul className="mt-2 flex flex-col gap-2">
              {outcomes.map((outcome) => (
                <li key={outcome.outcome_id} className="text-text">
                  {outcome.title}
                  {outcome.description ? (
                    <span className="text-text-muted">
                      {" "}
                      — {outcome.description}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-text-muted">
            No outcomes yet — what results does this plan commit to?
          </p>
        )}
        {tasks.length > 0 ? (
          <div>
            <h3 className="font-semibold text-text">Tasks</h3>
            <ul className="mt-2 flex flex-col gap-2">
              {tasks.map((task) => (
                <li
                  key={task.task_id}
                  className="rounded-md bg-surface-muted p-3"
                >
                  <span className="font-semibold text-text">
                    {task.title}
                  </span>
                  {task.duration_hours !== null ? (
                    <span className="text-text-muted">
                      {" "}
                      · {formatHours(task.duration_hours)}
                    </span>
                  ) : (
                    <span className="text-text-muted"> · unestimated</span>
                  )}
                  {task.deadline ? (
                    <span className="text-text-muted">
                      {" "}
                      · due {formatDate(task.deadline)}
                    </span>
                  ) : null}
                  {taskEdit ? taskEdit(task) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-text-muted">
            No tasks yet — the work that executes the outcomes.
          </p>
        )}
      </div>
    </Card>
  );
}
