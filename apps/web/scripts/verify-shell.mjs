// Structural checks for the app shell (TASK-104).
//
// The web app has no JS test runner in the technology baseline
// (ADR-007 pins next/react/typescript only), so the shell's
// automated tests are these filesystem assertions plus
// `tsc --noEmit` (both under `npm run verify`) and `next build`.
// They pin what the shell promises: the root layout with its
// landmarks and skip link, the header navigation, and the goals
// home route.

import { readFile, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const failures = [];

function check(condition, message) {
  if (!condition) {
    failures.push(message);
  }
}

async function read(relativePath) {
  return readFile(join(webRoot, relativePath), "utf8");
}

async function exists(relativePath) {
  try {
    await stat(join(webRoot, relativePath));
    return true;
  } catch {
    return false;
  }
}

const layout = await read("src/app/layout.tsx");
check(layout.includes('lang="en"'), "root layout sets lang");
check(
  layout.includes('href="#main-content"'),
  "root layout has a skip link to main content",
);
check(layout.includes("<SiteHeader />"), "root layout renders the site header");
check(
  layout.includes('id="main-content"'),
  "root layout marks the main landmark",
);

const header = await read("src/components/site-header.tsx");
check(
  header.includes('aria-label="Primary"'),
  "navigation is labelled",
);
check(
  header.includes('href="/"') && header.includes("Goals"),
  "navigation links the goals home",
);
check(
  header.includes('aria-current'),
  "navigation marks the current entry",
);

check(
  await exists("src/app/page.tsx"),
  "the goals home route exists",
);

// TASK-107 — goal creation: the home page composes the interactive
// board, which talks to the API through the /api proxy.
const page = await read("src/app/page.tsx");
check(
  page.includes("<GoalBoard />"),
  "the goals home renders the goal board",
);
check(
  await exists("src/components/goal-board.tsx"),
  "the goal board component exists",
);
const board = await read("src/components/goal-board.tsx");
check(
  board.startsWith('"use client"'),
  "the goal board is a client component",
);
check(
  board.includes("TextField") &&
    board.includes("Button") &&
    board.includes("Card"),
  "the goal board composes the design-system primitives",
);
check(
  board.includes("role=\"alert\""),
  "goal board errors are announced as alerts",
);
check(
  await exists("src/lib/goals.ts") && await exists("src/lib/user.ts"),
  "the goals API client and user-id convention exist",
);
const goalsClient = await read("src/lib/goals.ts");
check(
  goalsClient.includes("/api/goals"),
  "the goals client targets the proxied API path",
);
const nextConfig = await read("next.config.ts");
check(
  nextConfig.includes('"/api/:path*"'),
  "next.config rewrites /api/* to the backend",
);
check(
  nextConfig.includes("API_ORIGIN"),
  "the API origin is configurable via API_ORIGIN",
);

// TASK-108 — goal detail: the dynamic route renders server-side
// from the backend, and the board links into it.
check(
  await exists("src/app/goals/[goalId]/page.tsx"),
  "the goal detail route exists",
);
const detail = await read("src/app/goals/[goalId]/page.tsx");
check(
  detail.includes("notFound()"),
  "the goal detail renders not-found for unknown goals",
);
check(
  detail.includes('dynamic = "force-dynamic"'),
  "the goal detail renders per-request, never prerendered",
);
check(
  board.includes("`/goals/${goal.goal_id}`"),
  "the goal board links each goal to its detail page",
);
check(
  await exists("src/lib/server-api.ts"),
  "the server-side API helper exists",
);
const serverApi = await read("src/lib/server-api.ts");
check(
  serverApi.includes("API_ORIGIN"),
  "server-side fetch resolves the same API_ORIGIN knob",
);

// TASK-109 — backcast visualization: the detail page shows the
// current → gap → future chain, or the definition form when absent.
check(
  await exists("src/components/backcast-chain.tsx") &&
    await exists("src/components/backcast-form.tsx"),
  "the backcast chain and form components exist",
);
check(
  await exists("src/lib/backcast.ts"),
  "the backcast API client exists",
);
const backcastClient = await read("src/lib/backcast.ts");
check(
  backcastClient.includes("/api/goals/${goalId}/backcast") ||
    backcastClient.includes("`/api/goals/${goalId}/backcast`"),
  "the backcast client targets the proxied API path",
);
const updatedDetail = await read("src/app/goals/[goalId]/page.tsx");
check(
  updatedDetail.includes("BackcastForm") &&
    updatedDetail.includes("BackcastChain"),
  "the goal detail composes the backcast form and chain",
);
const chain = await read("src/components/backcast-chain.tsx");
check(
  !chain.startsWith('"use client"'),
  "the backcast chain renders on the server",
);
const backcastForm = await read("src/components/backcast-form.tsx");
check(
  backcastForm.startsWith('"use client"'),
  "the backcast form is a client component",
);
check(
  backcastForm.includes("router.refresh()"),
  "the backcast form refreshes the server-rendered page after submit",
);
check(
  backcastForm.includes("role=\"alert\""),
  "backcast form errors are announced as alerts",
);

// TASK-110 — milestone UI: checkpoints on the backcasting run.
check(
  await exists("src/components/milestone-list.tsx") &&
    await exists("src/components/milestone-form.tsx"),
  "the milestone list and form components exist",
);
check(
  await exists("src/lib/milestones.ts"),
  "the milestone API client exists",
);
const milestoneClient = await read("src/lib/milestones.ts");
check(
  milestoneClient.includes("`/api/goals/${goalId}/milestones`"),
  "the milestone client targets the proxied API path",
);
const milestoneDetail = await read("src/app/goals/[goalId]/page.tsx");
check(
  milestoneDetail.includes("MilestoneList") &&
    milestoneDetail.includes("MilestoneForm"),
  "the goal detail composes the milestone list and form",
);
const milestoneList = await read("src/components/milestone-list.tsx");
check(
  !milestoneList.startsWith('"use client"'),
  "the milestone list renders on the server",
);
check(
  milestoneList.includes("<ol"),
  "the milestone list is an ordered list (the path is walked in order)",
);
const milestoneForm = await read("src/components/milestone-form.tsx");
check(
  milestoneForm.startsWith('"use client"'),
  "the milestone form is a client component",
);
check(
  milestoneForm.includes("router.refresh()"),
  "the milestone form refreshes the server-rendered page after submit",
);

// TASK-111 — plan UI: the goal detail grows the plan section —
// begin from the finished run, assemble outcomes and tasks on the
// DRAFT, and publish with the computed workload.
check(
  await exists("src/components/plan-view.tsx") &&
    await exists("src/components/plan-forms.tsx"),
  "the plan view and forms components exist",
);
check(
  await exists("src/lib/plans.ts"),
  "the plan API client exists",
);
const planClient = await read("src/lib/plans.ts");
check(
  planClient.includes("`/api/goals/${goalId}/plan`"),
  "the plan client targets the proxied API path",
);
const planDetail = await read("src/app/goals/[goalId]/page.tsx");
check(
  planDetail.includes("PlanView") &&
    planDetail.includes("BeginPlanForm") &&
    planDetail.includes("AddOutcomeForm") &&
    planDetail.includes("AddTaskForm") &&
    planDetail.includes("PublishPlanButton"),
  "the goal detail composes the plan view and assembly forms",
);
check(
  planDetail.includes("/plan`") &&
    planDetail.includes('status === "draft"'),
  "the plan section follows the draft/published split",
);
const planView = await read("src/components/plan-view.tsx");
check(
  !planView.startsWith('"use client"'),
  "the plan view renders on the server",
);
check(
  planView.includes("workload_hours"),
  "the plan view shows the computed workload",
);
const planForms = await read("src/components/plan-forms.tsx");
check(
  planForms.startsWith('"use client"'),
  "the plan forms are client components",
);
check(
  planForms.includes("router.refresh()"),
  "the plan forms refresh the server-rendered page after submit",
);
check(
  planForms.includes("role=\"alert\""),
  "plan form errors are announced as alerts",
);

// TASK-112 — task UI: assembly-time task revision. Each task row on
// a DRAFT plan carries an edit form; creation gains a deadline
// field; the domain's omit-keeps-value semantics ride the PATCH.
check(
  await exists("src/components/task-forms.tsx"),
  "the task revision form component exists",
);
const taskForms = await read("src/components/task-forms.tsx");
check(
  taskForms.startsWith('"use client"'),
  "the task revision form is a client component",
);
check(
  taskForms.includes("reviseTask"),
  "the task revision form calls the revise client",
);
check(
  taskForms.includes("router.refresh()") ||
    taskForms.includes("usePlanAction"),
  "the task revision form refreshes via the shared plan action hook",
);
check(
  taskForms.includes('type="datetime-local"'),
  "the task revision form edits the deadline",
);
const planClient112 = await read("src/lib/plans.ts");
check(
  planClient112.includes("`/api/goals/${goalId}/plan/tasks/${taskId}`"),
  "the revise client targets the proxied task path",
);
const planView112 = await read("src/components/plan-view.tsx");
check(
  planView112.includes("taskEdit"),
  "the plan view can attach a per-task edit slot",
);
check(
  planView112.includes("task.deadline"),
  "the plan view shows task deadlines",
);
const taskDetail112 = await read("src/app/goals/[goalId]/page.tsx");
check(
  taskDetail112.includes("TaskEditForm"),
  "the goal detail attaches revision forms to draft task rows",
);
const planForms112 = await read("src/components/plan-forms.tsx");
check(
  planForms112.includes('type="datetime-local"'),
  "task creation offers a deadline field",
);

// TASK-113 — calendar UI: the user-scoped calendar joins the top
// level. The board resolves the browser-held user's calendar, lists
// events, surfaces conflicts, and places new events.
check(
  await exists("src/app/calendar/page.tsx"),
  "the calendar route exists",
);
const calendarPage = await read("src/app/calendar/page.tsx");
check(
  calendarPage.includes("<CalendarBoard />"),
  "the calendar page renders the calendar board",
);
check(
  await exists("src/components/calendar-board.tsx"),
  "the calendar board component exists",
);
const calendarBoard = await read("src/components/calendar-board.tsx");
check(
  calendarBoard.startsWith('"use client"'),
  "the calendar board is a client component (user id is browser-held)",
);
check(
  calendarBoard.includes("getCalendarForUser") &&
    calendarBoard.includes("browserUserId"),
  "the board resolves the user's calendar from the browser user id",
);
check(
  calendarBoard.includes("listConflicts"),
  "the board surfaces event conflicts",
);
check(
  calendarBoard.includes('type="datetime-local"'),
  "event placement uses datetime inputs",
);
check(
  calendarBoard.includes("role=\"alert\""),
  "calendar board errors are announced as alerts",
);
check(
  await exists("src/lib/calendars.ts"),
  "the calendar API client exists",
);
const calendarClient = await read("src/lib/calendars.ts");
check(
  calendarClient.includes("`/api/users/${userId}/calendar`") &&
    calendarClient.includes("`/api/calendars/${calendarId}/events`"),
  "the calendar client targets the proxied API paths",
);
const header113 = await read("src/components/site-header.tsx");
check(
  header113.includes('"/calendar"') && header113.includes("Calendar"),
  "navigation links the calendar",
);
check(
  header113.includes("usePathname"),
  "navigation marks the current entry from the pathname",
);

// TASK-114 — progress UI: the Actual side of docs/07's triad. The
// goal detail gains a progress section once a plan exists — record
// sittings of work, take snapshots, read the latest.
check(
  await exists("src/components/progress-view.tsx") &&
    await exists("src/components/progress-forms.tsx"),
  "the progress view and forms components exist",
);
check(
  await exists("src/lib/progress.ts"),
  "the progress API client exists",
);
const progressClient = await read("src/lib/progress.ts");
check(
  progressClient.includes("`/api/goals/${goalId}/executions`") &&
    progressClient.includes("`/api/goals/${goalId}/progress`"),
  "the progress client targets the proxied API paths",
);
const progressDetail = await read("src/app/goals/[goalId]/page.tsx");
check(
  progressDetail.includes("ProgressView") &&
    progressDetail.includes("RecordWorkForm") &&
    progressDetail.includes("TakeSnapshotButton"),
  "the goal detail composes the progress view and forms",
);
const progressView = await read("src/components/progress-view.tsx");
check(
  !progressView.startsWith('"use client"'),
  "the progress view renders on the server",
);
check(
  progressView.includes("actual_hours") &&
    progressView.includes("planned_hours") &&
    progressView.includes("completed_task_count"),
  "the progress view shows actual vs planned and completion",
);
const progressForms = await read("src/components/progress-forms.tsx");
check(
  progressForms.startsWith('"use client"'),
  "the progress forms are client components",
);
check(
  progressForms.includes("router.refresh()"),
  "the progress forms refresh the server-rendered page after submit",
);
check(
  progressForms.includes('type="datetime-local"'),
  "recording work uses datetime inputs",
);
check(
  progressForms.includes("role=\"alert\""),
  "progress form errors are announced as alerts",
);

// TASK-115 — replanning UI: docs/08's level 2 driven by hand on a
// plan past assembly. Each task row gains a replan form, the whole
// plan can be re-derived, and the version trail every meaningful
// replan owes reads alongside.
check(
  await exists("src/components/replan-forms.tsx") &&
    await exists("src/components/plan-versions.tsx"),
  "the replan forms and version list components exist",
);
check(
  await exists("src/lib/replanning.ts"),
  "the replanning API client exists",
);
const replanningClient = await read("src/lib/replanning.ts");
check(
  replanningClient.includes("`/api/goals/${goalId}/plan/replan/local`") &&
    replanningClient.includes("`/api/goals/${goalId}/plan/replan/global`"),
  "the replanning client targets the proxied replan paths",
);
const replanDetail = await read("src/app/goals/[goalId]/page.tsx");
check(
  replanDetail.includes("LocalReplanForm") &&
    replanDetail.includes("GlobalReplanForm") &&
    replanDetail.includes("PlanVersionList"),
  "the goal detail composes the replan forms and version list",
);
check(
  replanDetail.includes("isDraft") &&
    replanDetail.includes("PlanHistory"),
  "the replanning surface follows the draft/published split",
);
const replanForms = await read("src/components/replan-forms.tsx");
check(
  replanForms.startsWith('"use client"'),
  "the replan forms are client components",
);
check(
  replanForms.includes("replanTaskLocally") &&
    replanForms.includes("replanPlanGlobally"),
  "the replan forms call the replan clients",
);
check(
  replanForms.includes("router.refresh()") ||
    replanForms.includes("usePlanAction"),
  "the replan forms refresh via the shared plan action hook",
);
check(
  replanForms.includes('type="datetime-local"'),
  "the local replan form edits the deadline",
);
check(
  replanForms.includes("reason"),
  "the replan forms demand a reason — a replan is traced",
);
const versionList = await read("src/components/plan-versions.tsx");
check(
  !versionList.startsWith('"use client"'),
  "the version list renders on the server",
);
check(
  versionList.includes("reason") && versionList.includes("<ol"),
  "the version list is an ordered trail showing reasons",
);

// TASK-116 — AI assistant UI: docs/09's first operation in the
// product. The goal detail grows the assistant's card — every
// recorded reading with its provenance — and the ask button, with
// the server's honest failures surfaced (no provider wired is not
// hidden).
check(
  await exists("src/components/assistant-card.tsx") &&
    await exists("src/components/assistant-forms.tsx"),
  "the assistant card and form components exist",
);
check(
  await exists("src/lib/assistant.ts"),
  "the assistant API client exists",
);
const assistantClient = await read("src/lib/assistant.ts");
check(
  assistantClient.includes(
    "`/api/goals/${goalId}/assistant/interpretations`",
  ),
  "the assistant client targets the proxied API path",
);
const assistantDetail = await read("src/app/goals/[goalId]/page.tsx");
check(
  assistantDetail.includes("AssistantCard") &&
    assistantDetail.includes("InterpretGoalButton"),
  "the goal detail composes the assistant card and ask button",
);
const assistantCard = await read("src/components/assistant-card.tsx");
check(
  !assistantCard.startsWith('"use client"'),
  "the assistant card renders on the server",
);
check(
  assistantCard.includes("provider") && assistantCard.includes("model"),
  "the assistant card shows each reading's provenance",
);
const assistantForms = await read("src/components/assistant-forms.tsx");
check(
  assistantForms.startsWith('"use client"'),
  "the assistant form is a client component",
);
check(
  assistantForms.includes("interpretGoal"),
  "the assistant form calls the interpret client",
);
check(
  assistantForms.includes("router.refresh()"),
  "the assistant form refreshes the server-rendered page after submit",
);
check(
  assistantForms.includes('role="alert"'),
  "assistant errors are announced as alerts",
);

const pkg = JSON.parse(await read("package.json"));
check(
  pkg.dependencies.next === "16.3.5",
  "next is pinned to the ADR-007 baseline (16.3.5)",
);
check(
  pkg.dependencies.react === "19.3.0" &&
    pkg.dependencies["react-dom"] === "19.3.0",
  "react is pinned to the ADR-007 baseline (19.3.0)",
);
check(
  pkg.devDependencies.typescript === "5.9.3",
  "typescript is pinned to the ADR-007 baseline (5.9.3)",
);
check(
  pkg.devDependencies.tailwindcss === "4.3.3",
  "tailwind is pinned to the ADR-007 baseline (4.3.3) — wired by TASK-106",
);

if (failures.length > 0) {
  console.error("app shell verification failed:");
  for (const failure of failures) {
    console.error(`  - ${failure}`);
  }
  process.exit(1);
}
console.log("app shell verification: OK");
