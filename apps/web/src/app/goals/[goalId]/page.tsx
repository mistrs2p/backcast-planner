import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BackcastChain } from "@/components/backcast-chain";
import { BackcastForm } from "@/components/backcast-form";
import { MilestoneForm } from "@/components/milestone-form";
import { MilestoneList } from "@/components/milestone-list";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { BackcastView } from "@/lib/backcast";
import type { Goal } from "@/lib/goals";
import type { MilestoneView } from "@/lib/milestones";
import { serverGet } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Goal detail",
};

function formatDate(moment: string): string {
  return new Date(moment).toLocaleString();
}

/**
 * One goal (TASK-108) with its backcast (TASK-109) and the
 * milestones pinned on its run (TASK-110). Rendered on the server
 * from the backend's GET endpoints; an unknown goal renders Next's
 * not-found boundary. Before a backcast is defined, the definition
 * form stands in for the visualization; milestones appear once a
 * run exists to attach them to.
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
  const backcast = await serverGet<BackcastView>(
    `/goals/${goalId}/backcast`,
  );
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
      <div className="mt-6">
        <h2 id="backcast-heading" className="sr-only">
          Backcast
        </h2>
        {backcast === null ? (
          <BackcastForm goalId={goal.goal_id} />
        ) : (
          <div className="flex flex-col gap-6">
            <BackcastChain backcast={backcast} />
            <Milestones goalId={goal.goal_id} />
          </div>
        )}
      </div>
      <p className="mt-6">
        <ButtonLink variant="secondary" href="/">
          Back to goals
        </ButtonLink>
      </p>
    </section>
  );
}

async function Milestones({ goalId }: { goalId: string }) {
  const milestones = await serverGet<MilestoneView[]>(
    `/goals/${goalId}/milestones`,
  );
  return (
    <>
      <MilestoneList milestones={milestones ?? []} />
      <MilestoneForm goalId={goalId} />
    </>
  );
}
