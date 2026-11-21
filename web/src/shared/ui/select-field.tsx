import { ChevronDown } from "lucide-react";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";
import { select } from "./recipes";

interface SelectFieldProps extends Omit<React.ComponentProps<"select">, "id"> {
  id: string;
  label: string;
  hint?: string | undefined;
  error?: string | undefined;
}

/** A labelled native select whose hint and error are announced with it. */
export function SelectField({
  id,
  label,
  hint,
  error,
  className,
  children,
  ...props
}: SelectFieldProps) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ");
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-body font-medium">
        {label}
      </label>
      <div className="relative">
        <select
          id={id}
          name={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy || undefined}
          className={cn(select, className)}
          {...props}
        >
          {children}
        </select>
        <ChevronDown
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
        />
      </div>
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
