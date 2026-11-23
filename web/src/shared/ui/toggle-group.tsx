import { ToggleGroup as T } from "radix-ui";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";

/*
 * ToggleGroup (shadcn/ui on Radix, MIT), restyled as a segmented control: one bordered group, the
 * pressed item on the lamp's wash (`selection-soft`) with ink text (The One Lamp Rule: it is the
 * one lit thing in the group). Arrow keys move between items (roving focus). For a choice of a
 * few views or periods that lives in the URL (leaderboard metric, subject, period).
 */

function ToggleGroup({ className, ...props }: React.ComponentProps<typeof T.Root>) {
  return (
    <T.Root
      data-slot="toggle-group"
      className={cn(
        "inline-flex w-fit items-center gap-0.5 rounded-md border border-input bg-background p-0.5",
        className,
      )}
      {...props}
    />
  );
}

function ToggleGroupItem({ className, ...props }: React.ComponentProps<typeof T.Item>) {
  return (
    <T.Item
      data-slot="toggle-group-item"
      className={cn(
        "inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 rounded-sm px-3 text-body font-medium whitespace-nowrap text-muted-foreground outline-none transition-[background-color,color,transform] duration-(--dur-fast) ease-(--ease-out) focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 data-[state=on]:bg-selection-soft data-[state=on]:text-foreground fine:h-8 can-hover:hover:text-foreground [&_svg]:size-4 [&_svg]:shrink-0",
        className,
      )}
      {...props}
    />
  );
}

export { ToggleGroup, ToggleGroupItem };
