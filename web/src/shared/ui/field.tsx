import type * as React from "react";
import { cn } from "@/shared/lib/utils";
import { Input } from "@/shared/ui/input";
import { control } from "@/shared/ui/recipes";

interface FieldProps extends Omit<React.ComponentProps<"input">, "id"> {
  id: string;
  label: string;
  hint?: string | undefined;
  error?: string | undefined;
  /** Id of a form-level alert that explains this field too (a wrong password). */
  alertId?: string | undefined;
  /** A way on from the error (a link), shown after its text but not part of the description. */
  errorAction?: React.ReactNode;
}

/** A labelled input whose rule, error and form-level alert are all announced with it. */
export function Field({ id, label, hint, error, alertId, errorAction, ...props }: FieldProps) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`, alertId]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-body font-medium">
        {label}
      </label>
      <Input
        id={id}
        name={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        {...props}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-small text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p className="fade-in text-small font-medium text-destructive">
          <span id={`${id}-error`}>{error}</span>
          {errorAction && <> {errorAction}</>}
        </p>
      )}
    </div>
  );
}

interface TextareaFieldProps extends Omit<React.ComponentProps<"textarea">, "id"> {
  id: string;
  label: string;
  hint?: string | undefined;
  error?: string | undefined;
}

/** `Field` for several lines of text. */
export function TextareaField({ id, label, hint, error, className, ...props }: TextareaFieldProps) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ");
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-body font-medium">
        {label}
      </label>
      <textarea
        id={id}
        name={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        className={cn(control, "min-h-28 resize-y px-3 py-2 leading-6", className)}
        {...props}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-small text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="fade-in text-small font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
