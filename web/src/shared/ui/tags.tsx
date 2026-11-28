import { X } from "lucide-react";
import type * as React from "react";
import type { ReactNode } from "react";
import { cn } from "@/shared/lib/utils";
import { IconButton } from "./button";

/*
 * Tags (blocks-map §1 "tags", after the free kibo-ui `tags` composition's idea; own code): one chip
 * for every tag filter and every active filter, so they read as one family. A chip is 44 px high on
 * touch and 32 px with a mouse (the Large targets preference keeps 44 px), full round, on
 * `secondary`.
 *
 * - `onRemove` (+ `removeLabel`): a chip that says what narrows a list, with a remove IconButton
 *   (the table's active filters, the libraries a picker holds).
 * - `pressed` (+ `onClick`): a toggle chip, `aria-pressed`; picked is a solid `route` fill, not a
 *   tint, so it reads at a glance and without colour (the tag filters).
 * - neither: a plain chip.
 *
 * Put chips in a `TagList` (a `<ul>` named by `label`), each in its own `<li>`, unless they are
 * toggles in a `fieldset`.
 */

const base =
  "inline-flex h-11 max-w-full min-w-0 shrink-0 items-center gap-1.5 rounded-full fine:h-8";

/** A toggle reads like a choice (body text); a removable chip like a note about the list (small). */
const toggle =
  "cursor-pointer px-3 text-body outline-none transition-[background-color,scale] duration-(--dur-fast) ease-(--ease-out) focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-safe:active:scale-[0.97] fine:px-2.5";

type TagProps = {
  children: ReactNode;
  /** Something before the text: a LibraryMark, an icon (`aria-hidden`). */
  leading?: ReactNode;
  /** Monospace text (an ID, a path). */
  mono?: boolean;
  className?: string;
} & (
  | {
      /** Takes the filter or the value away; the chip then disappears. */
      onRemove: () => void;
      /** The remove button's name and tooltip: "Remove filter Tags: api". */
      removeLabel: string;
      pressed?: undefined;
      onClick?: undefined;
    }
  | {
      /** A toggle chip: on or off. */
      pressed: boolean;
      onClick: () => void;
      onRemove?: undefined;
      removeLabel?: undefined;
    }
  | { onRemove?: undefined; removeLabel?: undefined; pressed?: undefined; onClick?: undefined }
);

export function Tag({
  children,
  leading,
  mono = false,
  className,
  onRemove,
  removeLabel,
  pressed,
  onClick,
}: TagProps) {
  if (pressed !== undefined) {
    return (
      <button
        type="button"
        data-slot="tag"
        aria-pressed={pressed}
        onClick={onClick}
        className={cn(
          base,
          toggle,
          pressed
            ? "bg-route text-route-foreground"
            : "bg-secondary text-secondary-foreground can-hover:hover:bg-accent",
          mono && "font-mono",
          className,
        )}
      >
        {leading}
        {children}
      </button>
    );
  }
  return (
    <span
      data-slot="tag"
      className={cn(
        base,
        "bg-secondary pl-3 text-small font-medium text-muted-foreground",
        onRemove ? "pr-0.5 fine:pr-0" : "pr-3",
        className,
      )}
    >
      {leading}
      <span
        title={typeof children === "string" ? children : undefined}
        className={cn("min-w-0 truncate", mono && "font-mono")}
      >
        {children}
      </span>
      {onRemove && (
        <IconButton
          label={removeLabel ?? ""}
          size="icon-sm"
          motion="turn"
          className="rounded-full text-muted-foreground hover:bg-background/70"
          onClick={onRemove}
        >
          <X aria-hidden="true" />
        </IconButton>
      )}
    </span>
  );
}

/** Chips in a named list; put each chip in its own `<li>`. */
export function TagList({
  label,
  className,
  ...props
}: Omit<React.ComponentProps<"ul">, "aria-label"> & {
  /** The list's accessible name ("Active filters", "Chosen libraries"). */
  label: string;
}) {
  return (
    <ul
      aria-label={label}
      className={cn("flex flex-wrap items-center gap-2", className)}
      {...props}
    />
  );
}
