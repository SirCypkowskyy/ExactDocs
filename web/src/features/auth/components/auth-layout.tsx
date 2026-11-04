import type { ReactNode } from "react";

/** A verbatim quote, the way ExactDocs hands it to an agent: the words, and where they live. */
function Excerpt() {
  return (
    <figure aria-hidden="true" className="max-w-md">
      <blockquote className="font-serif text-xl leading-snug text-field-foreground">
        <mark className="rounded-sm bg-mark px-1 py-0.5 text-field-foreground [box-decoration-break:clone]">
          useEffect is a React Hook that lets you synchronize a component with an external system.
        </mark>
      </blockquote>
      <figcaption className="mt-4 text-sm text-field-muted">
        react 19.3.1, reference/useEffect
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
  return (
    <div className="grid min-h-dvh lg:grid-cols-[5fr_6fr]">
      <aside className="flex flex-col justify-between gap-16 bg-field px-6 py-5 text-field-foreground lg:px-14 lg:py-12">
        <p className="font-serif text-xl font-semibold tracking-tight">ExactDocs</p>
        <div className="hidden flex-col gap-12 lg:flex">
          <p className="max-w-md font-serif text-4xl leading-[1.1] tracking-tight">
            Documentation, word for word.
          </p>
          <Excerpt />
        </div>
      </aside>
      <main className="flex items-start px-6 py-10 sm:py-16 lg:items-center lg:px-20">
        <div className="w-full max-w-sm">
          <h1 className="rise font-serif text-3xl font-semibold tracking-tight">{title}</h1>
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
