import { AlertDialog as A } from "radix-ui";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";
import { buttonVariants } from "./button";
import { dialogOverlay, dialogPanel } from "./recipes";

/*
 * AlertDialog (shadcn/ui on Radix, MIT), restyled to the tokens: the one way to confirm
 * (DESIGN.md, "Confirm with AlertDialog"). `role="alertdialog"`; Cancel takes focus first; Escape
 * cancels; a click outside does nothing; the confirm is `destructive-solid` when it removes or
 * stops something. 12 px corners, fades and zooms from 0.95 in 180 ms (the fade only with
 * reduced motion). `ConfirmDialog` (confirm-dialog.tsx) builds the usual layout from these parts.
 */

function AlertDialog(props: React.ComponentProps<typeof A.Root>) {
  return <A.Root data-slot="alert-dialog" {...props} />;
}

function AlertDialogTrigger(props: React.ComponentProps<typeof A.Trigger>) {
  return <A.Trigger data-slot="alert-dialog-trigger" {...props} />;
}

function AlertDialogContent({ className, ...props }: React.ComponentProps<typeof A.Content>) {
  return (
    <A.Portal>
      <A.Overlay data-slot="alert-dialog-overlay" className={dialogOverlay} />
      <A.Content
        data-slot="alert-dialog-content"
        className={cn(dialogPanel, className)}
        {...props}
      />
    </A.Portal>
  );
}

function AlertDialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div data-slot="alert-dialog-header" className={cn("flex flex-col", className)} {...props} />
  );
}

function AlertDialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-dialog-footer"
      className={cn("mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)}
      {...props}
    />
  );
}

function AlertDialogTitle({ className, ...props }: React.ComponentProps<typeof A.Title>) {
  return (
    <A.Title
      data-slot="alert-dialog-title"
      className={cn("text-title font-semibold tracking-tight [overflow-wrap:anywhere]", className)}
      {...props}
    />
  );
}

function AlertDialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof A.Description>) {
  return (
    <A.Description
      data-slot="alert-dialog-description"
      className={cn("mt-2 text-body text-muted-foreground", className)}
      {...props}
    />
  );
}

/** The confirm: `destructive-solid` by default (it removes or stops something). */
function AlertDialogAction({
  className,
  variant = "destructive-solid",
  ...props
}: React.ComponentProps<typeof A.Action> & {
  variant?: "default" | "destructive-solid";
}) {
  return (
    <A.Action
      data-slot="alert-dialog-action"
      className={cn(buttonVariants({ variant }), className)}
      {...props}
    />
  );
}

/** Cancel: a ghost button, focused when the dialog opens. */
function AlertDialogCancel({ className, ...props }: React.ComponentProps<typeof A.Cancel>) {
  return (
    <A.Cancel
      data-slot="alert-dialog-cancel"
      className={cn(buttonVariants({ variant: "ghost" }), className)}
      {...props}
    />
  );
}

export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
};
