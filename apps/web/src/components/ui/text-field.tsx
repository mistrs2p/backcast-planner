import { useId, type ComponentProps } from "react";

export type TextFieldProps = Omit<ComponentProps<"input">, "id"> & {
  /** The field's accessible name; required — a field without a
   * label is a bug, not a style choice. */
  label: string;
  id?: string;
  hint?: string;
  error?: string;
};

/**
 * The text input primitive: a label, an input, and optional hint
 * and error, wired together accessibly (`htmlFor`/`id`,
 * `aria-describedby`, `aria-invalid`, and the error announced as a
 * live region so it reaches assistive tech when it appears).
 */
export function TextField({
  label,
  id,
  hint,
  error,
  className,
  ...rest
}: TextFieldProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const hintId = hint ? `${fieldId}-hint` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;
  const describedBy =
    [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={["field", className].filter(Boolean).join(" ")}>
      <label className="field__label" htmlFor={fieldId}>
        {label}
      </label>
      <input
        id={fieldId}
        className="field__input"
        aria-describedby={describedBy}
        aria-invalid={error ? true : undefined}
        {...rest}
      />
      {hint ? (
        <p id={hintId} className="field__hint">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
