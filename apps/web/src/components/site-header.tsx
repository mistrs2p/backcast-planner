"use client";

import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Goals" },
  { href: "/calendar", label: "Calendar" },
] as const;

/**
 * The shell's global navigation.
 *
 * The MVP opens on Goals — every goal-scoped area (backcast, plan,
 * tasks) lives inside a goal's detail view. The calendar is
 * user-scoped (TASK-113), so it joins the top level. Marking the
 * current entry needs the pathname, which only a client component
 * can see — the one piece of client state the shell carries.
 */
export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header>
      <a href="/" className="brand">
        Backcasting Planner
      </a>
      <nav aria-label="Primary">
        <ul>
          {NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <a
                href={item.href}
                aria-current={pathname === item.href ? "page" : undefined}
              >
                {item.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
