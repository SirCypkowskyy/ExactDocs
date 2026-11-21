import type { ReactNode, Ref } from "react";

/**
 * A whole page that stands in for one that could not be shown: not found, an error, no access.
 * It says what happened and offers the way on, centred in the sheet (DESIGN.md, States).
 */
export function StatusScreen({
  icon,
  title,
  headingRef,
  children,
  actions,
  alert = false,
}: {
  icon: ReactNode;
  title: string;
  headingRef?: Ref<HTMLHeadingElement>;
  children: ReactNode;
  actions?: ReactNode;
  /** The explanation is announced (an error that just happened). */
  alert?: boolean;
}) {
  return (
    <main id="main" className="grid flex-1 place-items-center px-6 py-16">
      <div className="flex max-w-md flex-col items-center text-center">
        <span className="mb-4 inline-flex size-11 items-center justify-center rounded-full bg-secondary text-muted-foreground [&_svg]:size-5">
          {icon}
        </span>
        <h1 ref={headingRef} tabIndex={-1} className="text-title font-semibold outline-none">
          {title}
        </h1>
        <div
          {...(alert && { role: "alert" })}
          className="mt-2 text-body text-pretty text-muted-foreground"
        >
          {children}
        </div>
        {actions && <div className="mt-6 flex flex-wrap justify-center gap-2">{actions}</div>}
      </div>
    </main>
  );
}
