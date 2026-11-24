import { AlertDialog, Dialog } from "radix-ui";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";
import { dialogOverlay, dialogPanel } from "./recipes";

export const DialogRoot = Dialog.Root;
export const DialogTrigger = Dialog.Trigger;
export const DialogTitle = ({ className, ...p }: React.ComponentProps<typeof Dialog.Title>) => (
  <Dialog.Title className={cn("text-title font-semibold tracking-tight", className)} {...p} />
);
export const DialogDescription = ({
  className,
  ...p
}: React.ComponentProps<typeof Dialog.Description>) => (
  <Dialog.Description className={cn("mt-2 text-body text-muted-foreground", className)} {...p} />
);

export function DialogContent({ className, ...p }: React.ComponentProps<typeof Dialog.Content>) {
  return (
    <Dialog.Portal>
      <Dialog.Overlay className={dialogOverlay} />
      <Dialog.Content className={cn(dialogPanel, className)} {...p} />
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
  <AlertDialog.Title className={cn("text-title font-semibold tracking-tight", className)} {...p} />
);
export const ConfirmDescription = ({
  className,
  ...p
}: React.ComponentProps<typeof AlertDialog.Description>) => (
  <AlertDialog.Description
    className={cn("mt-2 text-body text-muted-foreground", className)}
    {...p}
  />
);

export function ConfirmContent({
  className,
  ...p
}: React.ComponentProps<typeof AlertDialog.Content>) {
  return (
    <AlertDialog.Portal>
      <AlertDialog.Overlay className={dialogOverlay} />
      <AlertDialog.Content className={cn(dialogPanel, className)} {...p} />
    </AlertDialog.Portal>
  );
}
