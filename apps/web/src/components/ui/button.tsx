import type { ComponentProps } from "react";
import Link from "next/link";

type Variant = "primary" | "secondary" | "danger";

const VARIANT_CLASS: Record<Variant, string> = {
  primary: "button--primary",
  secondary: "button--secondary",
  danger: "button--danger",
};

export type ButtonProps = ComponentProps<"button"> & {
  variant?: Variant;
};

/**
 * The button primitive. Defaults to `type="button"` so a stray
 * primitive inside a form never submits it by accident; forms opt
 * in with an explicit `type="submit"`.
 */
export function Button({
  variant = "primary",
  type = "button",
  className,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={["button", VARIANT_CLASS[variant], className]
        .filter(Boolean)
        .join(" ")}
      {...rest}
    />
  );
}

export type ButtonLinkProps = ComponentProps<typeof Link> & {
  variant?: Variant;
};

/** The same affordance as {@link Button}, for internal navigation. */
export function ButtonLink({
  variant = "primary",
  className,
  ...rest
}: ButtonLinkProps) {
  return (
    <Link
      className={["button", VARIANT_CLASS[variant], className]
        .filter(Boolean)
        .join(" ")}
      {...rest}
    />
  );
}
