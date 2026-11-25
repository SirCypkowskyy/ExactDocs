import { cva, type VariantProps } from "class-variance-authority";
import { Check } from "lucide-react";
import type * as React from "react";
import { cloneElement, isValidElement } from "react";
import { cn } from "@/shared/lib/utils";
import { Spinner } from "./spinner";
import { Tooltip } from "./tooltip";

/*
 * One button vocabulary for the whole UI (DESIGN.md, Components):
 * - default: the one primary action of a screen, near-black (inverted in dark);
 * - outline: secondary actions, on the sheet;
 * - ghost: tertiary and toolbar actions;
 * - destructive: removal, outlined in the destructive colour (the filled form is only in the
 *   confirmation dialog);
 * - band: the square icon controls in the band (muted ink on the frame, press 0.94).
 * 44px on touch screens, 36px (sm: 32px) where there is a fine pointer. Press scales to 0.97.
 * A label that doesn't fit the width it is given wraps; the button never shrinks for its row.
 */
const buttonVariants = cva(
  "inline-flex cursor-pointer items-center justify-center max-w-full shrink-0 gap-2 rounded-md text-center text-body font-medium outline-none select-none transition-[background-color,border-color,color,transform] duration-(--dur-fast) ease-(--ease-out) focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 aria-disabled:cursor-progress aria-disabled:active:scale-100 [&_svg]:size-4 [&_svg]:shrink-0",
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
        band: "relative shrink-0 text-band-muted focus-visible:ring-offset-band active:scale-[0.94] disabled:opacity-40 data-[state=open]:bg-band-hover data-[state=open]:text-band-foreground can-hover:hover:bg-band-hover can-hover:hover:text-band-foreground [&_svg]:size-[1.125rem]",
      },
      size: {
        // At least 44/36 px, taller when a long label wraps in a narrow box (#576).
        default: "h-fit min-h-11 px-4 py-1.5 fine:min-h-9",
        sm: "h-fit min-h-11 px-3 py-1 fine:min-h-8",
        icon: "size-11 fine:size-9",
        "icon-sm": "size-11 fine:size-8",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export { buttonVariants };

type ButtonProps = React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    pending?: boolean;
    /**
     * A short "it worked" moment (Copied, Saved): the label fades out and a check draws itself in
     * its place (opacity and clip-path, so the width never changes), then the label comes back. Pass a boolean (see `useFlash`) to opt in; the label
     * stays in the accessible name, so say the outcome in a status line too.
     */
    done?: boolean;
  };

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
  done,
  children,
  ...props
}: ButtonProps) {
  const label = (
    <>
      {pending && <Spinner />}
      {children}
    </>
  );
  return (
    <button
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...(pending && { "aria-busy": true, "aria-disabled": true })}
      {...(done !== undefined && { "data-done": done && !pending ? "" : undefined })}
      {...props}
    >
      {done === undefined ? (
        label
      ) : (
        <span className="grid place-items-center">
          <span
            className={cn(
              "col-start-1 row-start-1 inline-flex items-center gap-2 transition-opacity duration-(--dur-fast) ease-(--ease-out)",
              done && !pending && "opacity-0",
            )}
          >
            {label}
          </span>
          {done && !pending && (
            // Mounted when it turns on, so it draws itself in once (icon-motion.css, `draw`).
            <Check aria-hidden="true" data-icon-motion="draw" className="col-start-1 row-start-1" />
          )}
        </span>
      )}
    </button>
  );
}

type IconButtonProps = Omit<ButtonProps, "aria-label" | "size" | "variant" | "children"> & {
  /** What the control does ("Copy link", "Next page"): its accessible name and its tooltip. */
  label: string;
  /** The icon (decorative: give it `aria-hidden`). */
  children: React.ReactNode;
  variant?: "ghost" | "outline" | "destructive" | "band";
  /** `icon` is 44 px on touch and 36 px with a mouse; `icon-sm` 32 px with a mouse (dense rows). */
  size?: "icon" | "icon-sm";
  /** A key or chord that does the same, shown in the tooltip. */
  shortcut?: string;
  tooltipSide?: "top" | "right" | "bottom" | "left";
  /** The icon's reaction (icon-motion.css): `forward`, `back`, `pop`, `refresh`, `warn`... */
  motion?: IconMotion;
};

/** The reactions of `src/app/icon-motion.css` (`data-icon-motion` on a lucide icon). */
export type IconMotion =
  | "forward"
  | "back"
  | "out"
  | "down"
  | "up"
  | "turn"
  | "cog"
  | "refresh"
  | "tilt"
  | "pop"
  | "warn"
  | "draw"
  | "alert";

/**
 * A button that shows only an icon (DESIGN.md, Buttons): the label is required and is both its
 * accessible name and its tooltip, so the two never say different things. `pending` swaps the
 * icon for the spinner; `done` swaps it for a check that draws in. `motion` puts the icon's
 * reaction on it (or set `data-icon-motion` on the icon yourself). It forwards every other prop and
 * its ref to the button, so it can be a Radix trigger (`<DropdownMenuTrigger asChild>`).
 */
function IconButton({
  label,
  shortcut,
  tooltipSide,
  variant = "ghost",
  size = "icon",
  pending = false,
  motion,
  children,
  ...props
}: IconButtonProps) {
  const icon =
    motion && isValidElement<{ "data-icon-motion"?: string }>(children)
      ? cloneElement(children, { "data-icon-motion": motion })
      : children;
  return (
    <Tooltip
      label={label}
      {...(shortcut && { shortcut })}
      {...(tooltipSide && { side: tooltipSide })}
    >
      <Button variant={variant} size={size} aria-label={label} pending={pending} {...props}>
        {pending ? null : icon}
      </Button>
    </Tooltip>
  );
}

export { Button, IconButton };
