import type * as React from "react";
import { cn } from "@/shared/lib/utils";

function Input({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-11 w-full rounded-md border border-input bg-secondary px-3 text-base outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 aria-invalid:border-destructive aria-invalid:ring-destructive/25 disabled:opacity-60",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
