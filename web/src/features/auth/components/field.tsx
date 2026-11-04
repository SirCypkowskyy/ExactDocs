import type * as React from "react";
import { Input } from "@/shared/ui/input";

interface FieldProps extends Omit<React.ComponentProps<"input">, "id"> {
  id: string;
  label: string;
  hint?: string | undefined;
  error?: string | undefined;
  /** Id of a form-level alert that explains this field too (a wrong password). */
  alertId?: string | undefined;
}

/** A labelled input whose rule, error and form-level alert are all announced with it. */
export function Field({ id, label, hint, error, alertId, ...props }: FieldProps) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`, alertId]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
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
        <p id={`${id}-hint`} className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="fade-in text-sm font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
