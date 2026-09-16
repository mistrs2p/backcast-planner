import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Goal } from "@/lib/goals";
import { serverGet } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Goal detail",
};

function formatDate(moment: string): string {
  return new Date(moment).toLocaleString();
}

/**
 * One goal, read-only (TASK-108). Rendered on the server from the
 * backend's GET /goals/{goal_id}; an unknown goal renders Next's
 * not-found boundary. Editing and lifecycle transitions come with
 * later EPIC-011 tasks; this view is the anchor they hang from.
 */
export default async function GoalDetailPage({
  params,
}: {
  params: Promise<{ goalId: string }>;
}) {
  const { goalId } = await params;
  const goal = await serverGet<Goal>(`/goals/${goalId}`);
  if (goal === null) {
    notFound();
  }
  return (
    <section aria-labelledby="goal-heading">
      <h1 id="goal-heading">{goal.title}</h1>
      <Card title="Details">
        <dl className="flex flex-col gap-3">
          <div>
            <dt className="text-sm font-semibold text-text-muted">Status</dt>
            <dd className="text-text">{goal.status}</dd>
          </div>
          <div>
            <dt className="text-sm font-semibold text-text-muted">
              Description
            </dt>
            <dd className="text-text">
              {goal.description || "No description yet."}
            </dd>
          </div>
          <div>
            <dt className="text-sm font-semibold text-text-muted">Created</dt>
            <dd className="text-text">{formatDate(goal.created_at)}</dd>
          </div>
          <div>
            <dt className="text-sm font-semibold text-text-muted">Updated</dt>
            <dd className="text-text">{formatDate(goal.updated_at)}</dd>
          </div>
        </dl>
      </Card>
      <p className="mt-6">
        <ButtonLink variant="secondary" href="/">
          Back to goals
        </ButtonLink>
      </p>
    </section>
  );
}
