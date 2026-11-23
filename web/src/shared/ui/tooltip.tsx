import { Tooltip as T } from "radix-ui";
import type * as React from "react";
import { createContext, useContext } from "react";
import { cn } from "@/shared/lib/utils";
import { kbd } from "./recipes";

/*
 * Tooltips (shadcn/ui on Radix): a short name for a control that shows only an icon, or the key
 * that does the same thing. They open after 400 ms on hover and at once on keyboard focus; once
 * one is open, the next opens instantly with no animation (Radix's `instant-open` state), so a
 * row of icon buttons reads like one labelled toolbar. The content scales in from the trigger.
 *
 * A tooltip never carries information that is not also in the control's accessible name.
 */

const Provided = createContext(false);

/** Mounted once in __root, so one open tooltip makes the next one instant. */
export function TooltipProvider({ children }: { children: React.ReactNode }) {
  return (
    <T.Provider delayDuration={400} skipDelayDuration={300}>
      <Provided.Provider value={true}>{children}</Provided.Provider>
    </T.Provider>
  );
}

type TooltipProps = {
  /** What the control does, in a few words ("Copy link", "Larger text"). */
  label: React.ReactNode;
  /** A key or chord that does the same thing, shown as a key hint. */
  shortcut?: string;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  /** The control. It must be a single element that accepts a ref (Radix `asChild`). */
  children: React.ReactElement;
  /** Show nothing (for example while a menu from the same trigger is open). */
  disabled?: boolean;
};

export function Tooltip({
  label,
  shortcut,
  side = "bottom",
  align = "center",
  children,
  disabled,
}: TooltipProps) {
  const provided = useContext(Provided);
  if (disabled) return children;
  const tip = (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          align={align}
          sideOffset={6}
          collisionPadding={8}
          className={cn(
            "z-60 flex max-w-64 origin-(--radix-tooltip-content-transform-origin) items-center gap-2 rounded-sm bg-tip px-2 py-1 text-small font-medium text-tip-foreground shadow-float select-none",
            "data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=delayed-open]:duration-(--dur-tip) data-[state=delayed-open]:ease-(--ease-out) motion-safe:data-[state=delayed-open]:zoom-in-[0.96]",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:duration-(--dur-exit)",
          )}
        >
          <span>{label}</span>
          {shortcut && (
            <kbd
              className={cn(kbd, "border-tip-foreground/25 bg-transparent text-tip-foreground/80")}
            >
              {shortcut}
            </kbd>
          )}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
  // Outside the app's provider (a component rendered on its own, as in a test) bring one along.
  return provided ? tip : <TooltipProvider>{tip}</TooltipProvider>;
}
