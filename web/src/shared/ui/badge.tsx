import type * as React from "react";
import { cn } from "@/shared/lib/utils";
import { pill, pillTone } from "./recipes";

/*
 * Badge (shadcn/ui's badge, MIT, rebuilt on the `pill` recipe): a status or a kind beside a value
 * (DESIGN.md, Pills and chips). 20 px high, full radius, 12 px / 500, a `-soft` ground with `-ink`
 * text. One status mark per row; states only on states (The Three Percent Rule).
 *
 * `count` is the number pill on a filter button or a nav entry ("State · 2"): tabular, at least
 * as wide as it is high.
 */

export type BadgeTone = keyof typeof pillTone;

export function Badge({
  tone = "neutral",
  count = false,
  className,
  ...props
}: React.ComponentProps<"span"> & { tone?: BadgeTone; count?: boolean }) {
  return (
    <span
      data-slot="badge"
      data-tone={tone}
      className={cn(pill, pillTone[tone], count && "num min-w-5 justify-center px-1.5", className)}
      {...props}
    />
  );
}
