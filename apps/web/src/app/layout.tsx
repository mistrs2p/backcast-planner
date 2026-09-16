import type { Metadata } from "next";
import type { ReactNode } from "react";
import { SiteHeader } from "@/components/site-header";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Backcasting Planner",
    template: "%s — Backcasting Planner",
  },
  description:
    "Define where you want to be; the system works backwards to determine " +
    "what must happen and what you can do now, then adapts as reality changes.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main-content">
          Skip to main content
        </a>
        <SiteHeader />
        <main id="main-content">{children}</main>
        <footer>
          <p>Backcasting Planner — plan backwards from the future you want.</p>
        </footer>
      </body>
    </html>
  );
}
