import type { ReactNode } from "react";
import { usePageTitle } from "@/shared/lib/use-page-title";

/** A verbatim quote, the way ExactDocs hands it to an agent: the words, and where they live. */
function Excerpt() {
  return (
    <figure aria-hidden="true" className="max-w-lg">
      <blockquote className="font-serif text-2xl leading-snug text-field-foreground">
        <mark className="rounded-sm bg-mark px-1 py-0.5 text-field-foreground [box-decoration-break:clone]">
          useEffect is a React Hook that lets you synchronize a component with an external system.
        </mark>
      </blockquote>
      <figcaption className="mt-4 font-mono text-xs text-field-muted">
        react@19.3.1 · reference/useEffect
      </figcaption>
    </figure>
  );
}

/** Two-column frame for setup and sign-in: an ink field with the product's promise, the form beside it. */
export function AuthLayout({
  title,
  intro,
  children,
}: {
  title: string;
  intro: string;
  children: ReactNode;
}) {
  const heading = usePageTitle(title);
  return (
    <div className="grid min-h-dvh grid-rows-[auto_1fr] lg:grid-cols-[5fr_6fr] lg:grid-rows-none">
      <aside className="flex h-16 flex-col justify-center bg-field px-6 text-field-foreground lg:h-auto lg:justify-between lg:px-14 lg:py-12">
        <p className="font-serif text-xl font-semibold tracking-tight">ExactDocs</p>
        <div className="hidden flex-col gap-12 lg:flex">
          <p className="max-w-[14ch] text-balance font-serif text-5xl leading-[1.05] tracking-tight">
            Documentation, word for word.
          </p>
          <Excerpt />
        </div>
      </aside>
      <main className="flex items-start px-6 py-10 sm:py-16 lg:items-center lg:justify-center lg:px-14">
        <div className="w-full max-w-sm">
          <h1
            ref={heading}
            tabIndex={-1}
            className="rise font-serif text-3xl font-semibold tracking-tight outline-none"
          >
            {title}
          </h1>
          <p
            className="rise mt-2 text-muted-foreground"
            style={{ "--i": 1 } as React.CSSProperties}
          >
            {intro}
          </p>
          <div className="rise mt-8" style={{ "--i": 2 } as React.CSSProperties}>
            {children}
          </div>
        </div>
      </main>
    </div>
  );
}
