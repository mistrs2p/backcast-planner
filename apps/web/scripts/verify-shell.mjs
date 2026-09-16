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
