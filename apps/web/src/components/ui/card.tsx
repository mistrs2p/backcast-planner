import type { ComponentProps, ReactNode } from "react";

export type CardProps = ComponentProps<"section"> & {
  title?: string;
  actions?: ReactNode;
};

/**
 * The surface primitive: a titled box for grouping related
 * content. The heading is level-agnostic on purpose — pages own
 * their heading hierarchy and pass the level via `children` when
 * the title needs one.
 */
export function Card({
  title,
  actions,
  className,
  children,
  ...rest
}: CardProps) {
  return (
    <section
      className={["card", className].filter(Boolean).join(" ")}
      {...rest}
    >
      {title ? (
        <div className="card__header">
          <h2 className="card__title">{title}</h2>
          {actions ? <div className="card__actions">{actions}</div> : null}
        </div>
      ) : null}
      <div className="card__body">{children}</div>
    </section>
  );
}
