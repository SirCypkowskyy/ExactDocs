import type * as React from "react";
import { cn } from "@/shared/lib/utils";
import { control, controlHeight } from "./recipes";

function Input({ className, ...props }: React.ComponentProps<"input">) {
  return <input className={cn(control, controlHeight, "px-3", className)} {...props} />;
}

export { Input };
