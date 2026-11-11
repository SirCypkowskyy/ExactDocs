import { ChevronDown } from "lucide-react";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";

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
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="relative">
        <select
          id={id}
          name={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy || undefined}
          className={cn(
            "h-11 w-full cursor-pointer appearance-none rounded-md border border-input bg-secondary pr-10 pl-3 text-base outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 aria-invalid:border-destructive disabled:cursor-not-allowed disabled:opacity-60",
            className,
          )}
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
