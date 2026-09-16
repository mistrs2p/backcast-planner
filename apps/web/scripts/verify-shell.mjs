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
