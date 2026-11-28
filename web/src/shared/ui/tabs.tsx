import { Tabs as T } from "radix-ui";
import { type ComponentProps, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/shared/lib/utils";

/*
 * Underline tabs (shadcn/ui on Radix). The 2px indicator is one element that slides to the active
 * tab with transform (composite only, interruptible), as wide as its label; with reduced motion it
 * moves at once. Keyboard: arrows move between tabs, as Radix provides.
 */

export const Tabs = T.Root;

/**
 * A tab's panel. Radix makes it focusable (Tab from the tab list lands on it when its first
 * content is text), so it shows the focus ring like any control.
 */
export function TabsContent({ className, ...props }: ComponentProps<typeof T.Content>) {
  return (
    <T.Content
      className={cn(
        "rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 focus-visible:ring-offset-background",
        className,
      )}
      {...props}
    />
  );
}

export function TabsList({ className, children, ...props }: ComponentProps<typeof T.List>) {
  const ref = useRef<HTMLDivElement>(null);
  const [bar, setBar] = useState<{ x: number; y: number; w: number } | null>(null);

  useLayoutEffect(() => {
    const list = ref.current;
    if (!list) return;
    const measure = () => {
      const active = list.querySelector<HTMLElement>('[role="tab"][data-state="active"]');
      // Under the active tab, on its row: the tabs wrap when they don't fit (#576).
      if (active) {
        setBar({
          x: active.offsetLeft,
          y: active.offsetTop + active.offsetHeight,
          w: active.offsetWidth,
        });
      }
    };
    measure();
    const observer = new MutationObserver(measure);
    observer.observe(list, { subtree: true, attributes: true, attributeFilter: ["data-state"] });
    const resize = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    resize?.observe(list);
    return () => {
      observer.disconnect();
      resize?.disconnect();
    };
  }, []);

  return (
    <T.List
      ref={ref}
      className={cn("relative flex flex-wrap gap-1 border-b border-border", className)}
      {...props}
    >
      {children}
      {bar && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute top-0 left-0 h-0.5 w-px origin-left rounded-full bg-route transition-transform duration-(--dur) ease-(--ease-out) motion-reduce:transition-none"
          style={{ transform: `translate(${bar.x}px, ${bar.y - 1}px) scaleX(${bar.w})` }}
        />
      )}
    </T.List>
  );
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn(
        "relative inline-flex h-11 cursor-pointer items-center gap-2 rounded-t-md px-3 text-body font-medium text-muted-foreground outline-none transition-[color,scale] duration-(--dur-fast) ease-(--ease-out) motion-safe:active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:text-foreground fine:h-10 can-hover:hover:text-foreground [&_svg]:size-4",
        className,
      )}
      {...props}
    />
  );
}
