import { Popover as P } from "radix-ui";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";

/*
 * Popover (shadcn/ui on Radix, MIT), restyled to the tokens: a floating card like a menu
 * (`popover` ground, hairline, 8 px corners, `shadow-float`) that scales in from its trigger
 * (0.97, 150 ms in, 100 ms out; the fade only with reduced motion). For pickers and filters that
 * need more than a list of commands (Command inside, a form, a short explanation).
 */

function Popover(props: React.ComponentProps<typeof P.Root>) {
  return <P.Root data-slot="popover" {...props} />;
}

function PopoverTrigger(props: React.ComponentProps<typeof P.Trigger>) {
  return <P.Trigger data-slot="popover-trigger" {...props} />;
}

function PopoverAnchor(props: React.ComponentProps<typeof P.Anchor>) {
  return <P.Anchor data-slot="popover-anchor" {...props} />;
}

function PopoverContent({
  className,
  align = "start",
  sideOffset = 6,
  ...props
}: React.ComponentProps<typeof P.Content>) {
  return (
    <P.Portal>
      <P.Content
        data-slot="popover-content"
        align={align}
        sideOffset={sideOffset}
        collisionPadding={8}
        className={cn(
          "z-50 max-h-(--radix-popover-content-available-height) w-72 origin-(--radix-popover-content-transform-origin) overflow-y-auto rounded-lg border border-border bg-popover p-4 text-popover-foreground shadow-float outline-none",
          "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-(--dur-menu) data-[state=open]:ease-(--ease-out) motion-safe:data-[state=open]:zoom-in-[0.97]",
          "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:duration-(--dur-exit) motion-safe:data-[state=closed]:zoom-out-[0.98]",
          className,
        )}
        {...props}
      />
    </P.Portal>
  );
}

export { Popover, PopoverAnchor, PopoverContent, PopoverTrigger };
