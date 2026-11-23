import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";
import { Spinner } from "./spinner";

/*
 * One button vocabulary for the whole UI (DESIGN.md, Components):
 * - default: the one primary action of a screen, near-black (inverted in dark);
 * - outline: secondary actions, on the sheet;
 * - ghost: tertiary and toolbar actions;
 * - destructive: removal, outlined in the destructive colour (the filled form is only in the
 *   confirmation dialog).
 * 44px on touch screens, 36px (sm: 32px) where there is a fine pointer. Press scales to 0.97.
 */
const buttonVariants = cva(
  "inline-flex cursor-pointer items-center justify-center gap-2 rounded-md text-body font-medium whitespace-nowrap outline-none select-none transition-[background-color,border-color,color,transform] duration-(--dur-fast) ease-(--ease-out) focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 aria-disabled:cursor-progress aria-disabled:active:scale-100 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground hover:bg-primary/88 aria-disabled:bg-primary/75",
        outline:
          "border border-input bg-background text-foreground hover:border-muted-foreground/40 hover:bg-accent aria-disabled:bg-accent",
        ghost: "text-foreground hover:bg-accent aria-disabled:bg-accent",
        destructive:
          "border border-destructive/40 bg-background text-destructive hover:border-destructive hover:bg-destructive-soft",
        "destructive-solid":
          "bg-destructive text-white hover:bg-destructive/90 dark:text-background aria-disabled:bg-destructive/75",
      },
      size: {
        default: "h-11 px-4 [@media(pointer:fine)]:h-9",
        sm: "h-11 px-3 [@media(pointer:fine)]:h-8",
        icon: "size-11 [@media(pointer:fine)]:size-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export { buttonVariants };

/**
 * `pending` keeps the label (so the button does not change width), shows a spinner in place of
 * the leading icon and marks the button busy; clicks still arrive, so the handler must ignore them.
 */
function Button({
  className,
  variant,
  size,
  type = "button",
  pending = false,
  children,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { pending?: boolean }) {
  return (
    <button
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...(pending && { "aria-busy": true, "aria-disabled": true })}
      {...props}
    >
      {pending && <Spinner />}
      {children}
    </button>
  );
}

export { Button };
