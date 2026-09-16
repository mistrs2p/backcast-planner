const NAV_ITEMS = [
  { href: "/", label: "Goals" },
] as const;

/**
 * The shell's global navigation.
 *
 * The MVP opens on Goals — every other area (backcast, plan,
 * schedule, progress) lives inside a goal's detail view, so the
 * top level stays a single entry point. Server component on
 * purpose: the shell has no client state.
 */
export function SiteHeader() {
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
                aria-current={item.href === "/" ? "page" : undefined}
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
