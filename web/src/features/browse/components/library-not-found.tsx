import { Link } from "@tanstack/react-router";
import { usePageTitle } from "@/shared/lib/use-page-title";

/** The address names a library this instance does not have (or the caller may not see). */
export function LibraryNotFound({ owner, repo }: { owner: string; repo: string }) {
  const heading = usePageTitle("Library not found");
  return (
    <main className="flex flex-col items-start gap-3 px-4 py-8 sm:px-6 sm:py-10 2xl:mx-auto 2xl:max-w-[96rem]">
      <h1
        ref={heading}
        tabIndex={-1}
        className="font-serif text-3xl font-semibold tracking-tight outline-none"
      >
        Library not found
      </h1>
      <p className="max-w-prose text-pretty text-muted-foreground">
        ExactDocs has no library{" "}
        <code className="font-mono text-foreground">
          {owner}/{repo}
        </code>
        . Check the address, or pick one from the list.
      </p>
      <Link
        to="/"
        className="inline-flex h-11 items-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground outline-none transition-[background-color,transform] duration-150 hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.97]"
      >
        All libraries
      </Link>
    </main>
  );
}
