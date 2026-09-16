import type { Metadata } from "next";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TextField } from "@/components/ui/text-field";

export const metadata: Metadata = {
  title: "Design system",
};

/**
 * The living style guide: every primitive rendered against the
 * tokens, so a regression in either is visible on one page — and
 * so `next build` plus the verify script exercise the primitives
 * the feature UIs (TASK-107+) will compose.
 */
export default function DesignPage() {
  return (
    <section aria-labelledby="design-heading">
      <h1 id="design-heading">Design system</h1>

      <Card title="Buttons">
        <div
          style={{
            display: "flex",
            gap: "var(--space-4)",
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="danger">Danger</Button>
          <Button disabled>Disabled</Button>
          <ButtonLink href="/">Link</ButtonLink>
        </div>
      </Card>

      <Card title="Fields">
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "var(--space-5)",
          }}
        >
          <TextField label="Goal title" hint="One clear sentence." />
          <TextField
            label="Target date"
            error="A goal needs a future to aim at."
          />
        </div>
      </Card>

      <Card title="A card" actions={<Button variant="secondary">Act</Button>}>
        <p>
          Cards group related content on the token palette; they are
          the surface the feature UIs compose.
        </p>
      </Card>
    </section>
  );
}
