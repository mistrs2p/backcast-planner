import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BackcastChain } from "@/components/backcast-chain";
import { BackcastForm } from "@/components/backcast-form";
import { MilestoneForm } from "@/components/milestone-form";
import { MilestoneList } from "@/components/milestone-list";
import { PlanVersionList } from "@/components/plan-versions";
import {
  AddOutcomeForm,
  AddTaskForm,
  BeginPlanForm,
  PublishPlanButton,
} from "@/components/plan-forms";
import { PlanView } from "@/components/plan-view";
import {
  GlobalReplanForm,
  LocalReplanForm,
} from "@/components/replan-forms";
import {
  RecordWorkForm,
  TakeSnapshotButton,
} from "@/components/progress-forms";
import { ProgressView } from "@/components/progress-view";
import { TaskEditForm } from "@/components/task-forms";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { BackcastView } from "@/lib/backcast";
import type { Goal } from "@/lib/goals";
import type { MilestoneView } from "@/lib/milestones";
import type { PlanBundleView } from "@/lib/plans";
import type { ProgressView as ProgressSnapshotView } from "@/lib/progress";
import type { PlanVersionView } from "@/lib/replanning";
import { serverGet } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Goal detail",
};

function formatDate(moment: string): string {
  return new Date(moment).toLocaleString();
}

/**
 * One goal (TASK-108) with its backcast (TASK-109), the milestones
 * pinned on its run (TASK-110), the plan executing it (TASK-111)
 * — whose tasks stay revisable while the plan is a DRAFT
 * (TASK-112) and replannable once it is published, with every
 * meaningful replan traced as a plan version (TASK-115) — and the
 * progress of actually doing it (TASK-114). Rendered on the server
 * from the backend's GET endpoints; an unknown goal renders Next's
 * not-found boundary. Before a backcast is defined, the definition
 * form stands in for the visualization; milestones and the plan
 * follow from the run.
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
            <Plan goalId={goal.goal_id} />
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

async function Plan({ goalId }: { goalId: string }) {
  const bundle = await serverGet<PlanBundleView>(`/goals/${goalId}/plan`);
  if (bundle === null) {
    return <BeginPlanForm goalId={goalId} />;
  }
  const isDraft = bundle.plan.status === "draft";
  const hasEstimatedTask = bundle.tasks.some(
    (task) => task.duration_hours !== null,
  );
  return (
    <>
      <PlanView
        bundle={bundle}
        taskEdit={
          isDraft
            ? (task) => <TaskEditForm goalId={goalId} task={task} />
            : (task) => <LocalReplanForm goalId={goalId} task={task} />
        }
      />
      {isDraft ? (
        <>
          <AddOutcomeForm goalId={goalId} />
          <AddTaskForm goalId={goalId} outcomes={bundle.outcomes} />
          <PublishPlanButton
            goalId={goalId}
            disabled={!hasEstimatedTask}
          />
        </>
      ) : (
        <PlanHistory goalId={goalId} />
      )}
      <Progress goalId={goalId} tasks={bundle.tasks} />
    </>
  );
}

async function PlanHistory({ goalId }: { goalId: string }) {
  const versions = await serverGet<PlanVersionView[]>(
    `/goals/${goalId}/plan/versions`,
  );
  return (
    <>
      <PlanVersionList versions={versions ?? []} />
      <GlobalReplanForm goalId={goalId} />
    </>
  );
}

async function Progress({
  goalId,
  tasks,
}: {
  goalId: string;
  tasks: PlanBundleView["tasks"];
}) {
  const progress = await serverGet<ProgressSnapshotView>(
    `/goals/${goalId}/progress`,
  );
  return (
    <>
      {progress !== null ? (
        <ProgressView progress={progress} />
      ) : (
        <Card title="Progress">
          <p className="text-text-muted">
            No progress snapshot yet — record work as it happens, then
            take one.
          </p>
        </Card>
      )}
      {tasks.length > 0 ? (
        <RecordWorkForm goalId={goalId} tasks={tasks} />
      ) : null}
      <TakeSnapshotButton goalId={goalId} />
    </>
  );
}
