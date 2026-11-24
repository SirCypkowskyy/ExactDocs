import type { ReactNode, Ref } from "react";
import { cn } from "@/shared/lib/utils";

/*
 * Page frame (DESIGN.md, Layout). Two widths only: `operate` (lists, settings, forms: 1152px) and
 * `wide` (the library page and its reader, the full sheet). Every page starts with a PageHeader.
 */
export function Page({
  width = "operate",
  className,
  children,
  ...props
}: {
  width?: "operate" | "narrow" | "wide";
  className?: string;
  children: ReactNode;
} & Omit<React.ComponentProps<"main">, "className" | "children">) {
  return (
    <main
      id="main"
      className={cn(
        "mx-auto w-full px-4 pt-6 pb-16 sm:px-6 lg:px-8 lg:pt-8",
        width === "operate" && "max-w-[1152px]",
        width === "narrow" && "max-w-[720px]",
        width === "wide" && "max-w-none",
        className,
      )}
      {...props}
    >
      {children}
    </main>
  );
}

/** The title row: an h1 (focused on navigation by usePageTitle), one line about the data, and actions. */
export function PageHeader({
  title,
  icon,
  headingRef,
  description,
  actions,
  above,
  className,
}: {
  title: ReactNode;
  /** The page's own icon (the one its navigation entry uses), in a hairline tile beside the title. */
  icon?: ReactNode;
  headingRef?: Ref<HTMLHeadingElement>;
  description?: ReactNode;
  actions?: ReactNode;
  /** A breadcrumb or route strip above the title. */
  above?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-6 lg:mb-8", className)}>
      {above && <div className="mb-3">{above}</div>}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-1 basis-64 items-start gap-3">
          {icon && (
            <span
              aria-hidden="true"
              className="mt-0.5 inline-flex size-9 flex-none items-center justify-center rounded-lg border border-border bg-raised text-muted-foreground [&_svg]:size-[1.125rem]"
            >
              {icon}
            </span>
          )}
          <div className="min-w-0 flex-1">
            <h1
              ref={headingRef}
              tabIndex={-1}
              className="text-title font-semibold tracking-[-0.01em] text-balance outline-none"
            >
              {title}
            </h1>
            {description && (
              <div className="mt-1.5 max-w-[68ch] text-body text-muted-foreground">
                {description}
              </div>
            )}
          </div>
        </div>
        {actions && <div className="flex flex-none flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

/** A page section: a heading row with optional actions, then its content. */
export function Section({
  id,
  title,
  icon,
  description,
  actions,
  children,
  className,
  headingLevel = 2,
}: {
  id?: string;
  title: ReactNode;
  /** A small muted icon before the heading. */
  icon?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  headingLevel?: 2 | 3;
}) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section
      id={id}
      aria-labelledby={id && `${id}-title`}
      className={cn("scroll-mt-20", className)}
    >
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0 flex-1 basis-72">
          <Heading
            id={id && `${id}-title`}
            className="flex items-center gap-2 text-section font-semibold"
          >
            {icon && (
              <span aria-hidden="true" className="text-muted-foreground [&_svg]:size-4">
                {icon}
              </span>
            )}
            {title}
          </Heading>
          {description && (
            <div className="mt-1 max-w-[68ch] text-body text-muted-foreground">{description}</div>
          )}
        </div>
        {actions && <div className="flex flex-none items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

/**
 * An empty or first-run state that says what to do next; it keeps the block's frame. The icon is
 * large and muted (32 px, a 1.5 stroke, like a table's empty frame) and does not move.
 */
export function EmptyState({
  title,
  children,
  action,
  icon,
  className,
  headingLevel,
  role,
}: {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
  /** The title as a heading (the page's main answer, e.g. "No results"); a line of text otherwise. */
  headingLevel?: 2 | 3;
  /** `alert` when it says something failed. */
  role?: "alert";
}) {
  const Heading = headingLevel === 2 ? "h2" : headingLevel === 3 ? "h3" : "p";
  return (
    <div
      role={role}
      className={cn(
        "flex flex-col items-start gap-3 rounded-lg border border-dashed border-input px-5 py-6",
        className,
      )}
    >
      {icon && (
        <div
          data-slot="empty-icon"
          className="text-muted-foreground [&_svg]:size-8 [&_svg]:[stroke-width:1.5]"
        >
          {icon}
        </div>
      )}
      <div>
        <Heading className={headingLevel ? "text-section font-semibold" : "text-body font-medium"}>
          {title}
        </Heading>
        {children && (
          <div className="mt-1 max-w-[60ch] text-body text-muted-foreground">{children}</div>
        )}
      </div>
      {action}
    </div>
  );
}
