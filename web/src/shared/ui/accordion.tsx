import { ChevronDownIcon } from "lucide-react";
import { Accordion as A } from "radix-ui";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";

/*
 * Accordion (shadcn/ui on Radix): the phone's navigation groups (after the free shadcnblocks
 * navbars). The panel opens with a fade and the chevron turns; nothing animates a height.
 */

export const Accordion = A.Root;

export function AccordionItem({ className, ...props }: React.ComponentProps<typeof A.Item>) {
  return <A.Item className={cn("border-b border-rule last:border-b-0", className)} {...props} />;
}

export function AccordionTrigger({
  className,
  children,
  ...props
}: React.ComponentProps<typeof A.Trigger>) {
  return (
    <A.Header className="flex">
      <A.Trigger
        className={cn(
          "flex min-h-11 flex-1 cursor-pointer items-center justify-between gap-3 rounded-md px-3 text-left text-section font-medium outline-none transition-[color,background-color,scale] duration-(--dur-fast) ease-(--ease-out) motion-safe:active:scale-[0.99] focus-visible:ring-2 focus-visible:ring-ring can-hover:hover:bg-accent [&[data-state=open]>svg]:rotate-180",
          className,
        )}
        {...props}
      >
        {children}
        <ChevronDownIcon
          aria-hidden="true"
          className="size-4 shrink-0 text-muted-foreground transition-transform duration-(--dur) ease-(--ease-out) motion-reduce:transition-none"
        />
      </A.Trigger>
    </A.Header>
  );
}

export function AccordionContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof A.Content>) {
  return (
    <A.Content
      className="overflow-hidden data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-(--dur)"
      {...props}
    >
      <div className={cn("pb-2", className)}>{children}</div>
    </A.Content>
  );
}
