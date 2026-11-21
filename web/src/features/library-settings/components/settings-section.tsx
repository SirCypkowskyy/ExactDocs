import type { ReactNode, Ref } from "react";

/**
 * One settings section: its title and one line of help on the left, its controls on the right
 * (stacked on a phone). Sections are told apart by a rule, not by boxes. The heading's id is
 * `<id>-heading`, which the section nav and the tests point at.
 */
export function SettingsSection({
  id,
  title,
  description,
  headingRef,
  children,
}: {
  id: string;
  title: ReactNode;
  description: ReactNode;
  headingRef?: Ref<HTMLHeadingElement>;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={`${id}-heading`}
      className="scroll-mt-20 border-t border-rule py-8 first:border-t-0 first:pt-0 lg:grid lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-x-10"
    >
      <header className="mb-5 lg:mb-0">
        <h2
          id={`${id}-heading`}
          ref={headingRef}
          tabIndex={-1}
          className="text-section font-semibold outline-none [scroll-margin-top:5rem]"
        >
          {title}
        </h2>
        <p className="mt-1 max-w-[60ch] text-body text-muted-foreground">{description}</p>
      </header>
      <div className="min-w-0 max-w-[40rem]">{children}</div>
    </section>
  );
}
