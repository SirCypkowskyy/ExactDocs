import { cva } from "class-variance-authority";
import { ChevronDownIcon } from "lucide-react";
import { NavigationMenu as N } from "radix-ui";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";

/*
 * Navigation menu (shadcn/ui on Radix, after the free shadcnblocks Navbar 1 / 5 / 35 blocks).
 * Triggers open panels of icon links on hover or click; the panel scales in from under its trigger
 * (150 ms in, 100 ms out) and moving between triggers slides the content, so a pass along the bar
 * reads as one surface. Arrow keys move between items; Escape closes. Reduced motion keeps fades.
 */

export function NavigationMenu({
  className,
  children,
  viewport = true,
  ...props
}: React.ComponentProps<typeof N.Root> & { viewport?: boolean }) {
  return (
    <N.Root
      data-viewport={viewport}
      className={cn(
        "group/navigation-menu relative flex max-w-max flex-1 items-center justify-center",
        className,
      )}
      {...props}
    >
      {children}
      {viewport && <NavigationMenuViewport />}
    </N.Root>
  );
}

export function NavigationMenuList({ className, ...props }: React.ComponentProps<typeof N.List>) {
  return (
    <N.List
      className={cn("group flex flex-1 list-none items-center justify-center gap-0.5", className)}
      {...props}
    />
  );
}

export function NavigationMenuItem({ className, ...props }: React.ComponentProps<typeof N.Item>) {
  return <N.Item className={cn("relative", className)} {...props} />;
}

/**
 * A top-level link or trigger in the band: muted at rest, ink on hover and when open, and a 2px
 * underline in `route` when its page (or one of its panel's pages) is the current one.
 */
export const navigationMenuTriggerStyle = cva(
  "group relative inline-flex h-11 w-max cursor-pointer items-center justify-center gap-1.5 rounded-md px-3 text-body font-medium text-band-muted outline-none transition-[color,background-color,scale] duration-(--dur-fast) ease-(--ease-out) motion-safe:active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-band-hover data-[state=open]:text-band-foreground aria-[current=page]:text-band-foreground data-[active=true]:text-band-foreground fine:h-9 can-hover:hover:bg-band-hover can-hover:hover:text-band-foreground after:pointer-events-none after:absolute after:inset-x-3 after:-bottom-[7px] after:h-0.5 after:origin-center after:scale-x-0 after:rounded-full after:bg-route after:transition-transform after:duration-(--dur) after:ease-(--ease-out) aria-[current=page]:after:scale-x-100 data-[active=true]:after:scale-x-100",
);

export function NavigationMenuTrigger({
  className,
  children,
  ...props
}: React.ComponentProps<typeof N.Trigger>) {
  return (
    <N.Trigger className={cn(navigationMenuTriggerStyle(), className)} {...props}>
      {children}
      <ChevronDownIcon
        aria-hidden="true"
        className="relative top-px size-3.5 transition-transform duration-(--dur) ease-(--ease-out) group-data-[state=open]:rotate-180 motion-reduce:transition-none"
      />
    </N.Trigger>
  );
}

export function NavigationMenuContent({
  className,
  ...props
}: React.ComponentProps<typeof N.Content>) {
  return (
    <N.Content
      className={cn(
        "top-0 left-0 w-full p-2 md:absolute md:w-auto",
        // moving between triggers slides the content sideways (Radix sets data-motion)
        "motion-safe:data-[motion=from-end]:animate-in motion-safe:data-[motion=from-end]:fade-in-0 motion-safe:data-[motion=from-end]:slide-in-from-right-8 motion-safe:data-[motion=from-start]:animate-in motion-safe:data-[motion=from-start]:fade-in-0 motion-safe:data-[motion=from-start]:slide-in-from-left-8 motion-safe:data-[motion=to-end]:animate-out motion-safe:data-[motion=to-end]:fade-out-0 motion-safe:data-[motion=to-end]:slide-out-to-right-8 motion-safe:data-[motion=to-start]:animate-out motion-safe:data-[motion=to-start]:fade-out-0 motion-safe:data-[motion=to-start]:slide-out-to-left-8 data-[motion]:duration-(--dur-menu) data-[motion]:ease-(--ease-out)",
        className,
      )}
      {...props}
    />
  );
}

export function NavigationMenuViewport({
  className,
  ...props
}: React.ComponentProps<typeof N.Viewport>) {
  return (
    <div className="absolute top-full left-0 isolate z-50 flex justify-center">
      <N.Viewport
        className={cn(
          "relative mt-2 h-(--radix-navigation-menu-viewport-height) w-full origin-[top_center] overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-float transition-[width,height] duration-(--dur-menu) ease-(--ease-out) md:w-(--radix-navigation-menu-viewport-width) motion-reduce:transition-none",
          "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-(--dur-menu) motion-safe:data-[state=open]:zoom-in-[0.97] data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:duration-(--dur-exit) motion-safe:data-[state=closed]:zoom-out-[0.98]",
          className,
        )}
        {...props}
      />
    </div>
  );
}

/** A bare Radix link, for a top-level item styled with `navigationMenuTriggerStyle`. */
export const NavigationMenuPlainLink = N.Link;

export function NavigationMenuLink({ className, ...props }: React.ComponentProps<typeof N.Link>) {
  return (
    <N.Link
      className={cn(
        "flex gap-3 rounded-md p-3 text-body outline-none transition-[color,background-color,scale] duration-(--dur-fast) ease-(--ease-out) motion-safe:active:scale-[0.99] focus-visible:ring-2 focus-visible:ring-ring data-[active=true]:bg-route-soft can-hover:hover:bg-accent",
        className,
      )}
      {...props}
    />
  );
}
