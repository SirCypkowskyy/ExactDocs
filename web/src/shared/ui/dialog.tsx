import { AlertDialog, Dialog } from "radix-ui";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";

const overlay =
  "fixed inset-0 z-50 bg-foreground/30 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:duration-200 data-[state=open]:ease-[cubic-bezier(0.23,1,0.32,1)] data-[state=closed]:duration-150";

// Centered (a modal is not anchored to a trigger); fast exit, slightly slower enter.
const panel =
  "fixed top-1/2 left-1/2 z-50 max-sm:top-4 max-sm:translate-y-0 max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-border bg-card p-6 text-card-foreground shadow-lg outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-safe:data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 motion-safe:data-[state=closed]:zoom-out-95 data-[state=open]:duration-200 data-[state=open]:ease-[cubic-bezier(0.23,1,0.32,1)] data-[state=closed]:duration-150";

export const DialogRoot = Dialog.Root;
export const DialogTrigger = Dialog.Trigger;
export const DialogTitle = ({ className, ...p }: React.ComponentProps<typeof Dialog.Title>) => (
  <Dialog.Title
    className={cn("font-serif text-xl font-semibold tracking-tight", className)}
    {...p}
  />
);
export const DialogDescription = ({
  className,
  ...p
}: React.ComponentProps<typeof Dialog.Description>) => (
  <Dialog.Description className={cn("mt-2 text-sm text-muted-foreground", className)} {...p} />
);

export function DialogContent({ className, ...p }: React.ComponentProps<typeof Dialog.Content>) {
  return (
    <Dialog.Portal>
      <Dialog.Overlay className={overlay} />
      <Dialog.Content className={cn(panel, className)} {...p} />
    </Dialog.Portal>
  );
}

export const ConfirmRoot = AlertDialog.Root;
export const ConfirmCancel = AlertDialog.Cancel;
export const ConfirmAction = AlertDialog.Action;
export const ConfirmTitle = ({
  className,
  ...p
}: React.ComponentProps<typeof AlertDialog.Title>) => (
  <AlertDialog.Title
    className={cn("font-serif text-xl font-semibold tracking-tight", className)}
    {...p}
  />
);
export const ConfirmDescription = ({
  className,
  ...p
}: React.ComponentProps<typeof AlertDialog.Description>) => (
  <AlertDialog.Description className={cn("mt-2 text-sm text-muted-foreground", className)} {...p} />
);

export function ConfirmContent({
  className,
  ...p
}: React.ComponentProps<typeof AlertDialog.Content>) {
  return (
    <AlertDialog.Portal>
      <AlertDialog.Overlay className={overlay} />
      <AlertDialog.Content className={cn(panel, className)} {...p} />
    </AlertDialog.Portal>
  );
}
