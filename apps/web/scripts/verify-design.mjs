// Structural checks for the design system (TASK-105).
//
// Same approach as the shell: no JS test runner exists in the
// technology baseline, so the design system's automated tests are
// these assertions (chained into `npm run verify`) plus
// `tsc --noEmit` and `next build`. They pin what the design system
// promises: the token vocabulary, the accessible wiring of each
// primitive, and the showcase page that renders them all.

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

// --- Tokens ---

const tokens = await read("src/styles/tokens.css");
const TOKEN_NAMES = [
  "--color-bg",
  "--color-surface",
  "--color-surface-muted",
  "--color-text",
  "--color-text-muted",
  "--color-border",
  "--color-primary",
  "--color-primary-hover",
  "--color-on-primary",
  "--color-danger",
  "--color-danger-surface",
  "--color-focus",
  "--space-1",
  "--space-2",
  "--space-3",
  "--space-4",
  "--space-5",
  "--space-6",
  "--font-size-sm",
  "--font-size-md",
  "--font-size-lg",
  "--font-size-xl",
  "--font-size-2xl",
  "--font-weight-regular",
  "--font-weight-medium",
  "--font-weight-semibold",
  "--font-weight-bold",
  "--radius-sm",
  "--radius-md",
  "--radius-lg",
  "--shadow-card",
];
for (const token of TOKEN_NAMES) {
  check(tokens.includes(`${token}:`), `token ${token} is defined`);
}
check(
  tokens.includes("@media (prefers-color-scheme: dark)"),
  "the palette swaps for dark mode",
);
check(
  tokens.includes("--color-primary:") &&
    tokens.includes("--color-primary-hover:"),
  "interactive colors declare hover states",
);

// --- Primitives ---

const button = await read("src/components/ui/button.tsx");
check(
  button.includes('type = "button"'),
  "Button defaults to type=button — no accidental form submits",
);
check(
  button.includes("button--primary") &&
    button.includes("button--secondary") &&
    button.includes("button--danger"),
  "Button supports primary, secondary, and danger variants",
);
check(
  button.includes("ButtonLink"),
  "the button affordance exists for internal navigation",
);

const field = await read("src/components/ui/text-field.tsx");
check(
  field.includes("htmlFor={fieldId}"),
  "the field label is wired to the input",
);
check(
  field.includes("aria-describedby"),
  "hints and errors are described to assistive tech",
);
check(
  field.includes("aria-invalid"),
  "an error marks the input invalid",
);
check(
  field.includes('role="alert"'),
  "the error is announced when it appears",
);
check(
  field.includes("useId()"),
  "ids are generated when not supplied — labels never dangle",
);

check(await exists("src/components/ui/card.tsx"), "the card primitive exists");

// --- The living style guide ---

const showcase = await read("src/app/design/page.tsx");
check(
  showcase.includes("<Button>") &&
    showcase.includes('variant="secondary"') &&
    showcase.includes('variant="danger"'),
  "the showcase renders every button variant",
);
check(showcase.includes("<TextField"), "the showcase renders fields");
check(
  showcase.includes('label="Goal title"') &&
    showcase.includes('error="'),
  "the showcase renders a hint and an error",
);
check(showcase.includes("<Card"), "the showcase renders cards");

if (failures.length > 0) {
  console.error("design system verification failed:");
  for (const failure of failures) {
    console.error(`  - ${failure}`);
  }
  process.exit(1);
}
console.log("design system verification: OK");
