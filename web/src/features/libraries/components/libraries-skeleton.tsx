const widths = ["w-40", "w-56", "w-32", "w-48", "w-36"];

/** Shape of the list while it loads, so the page does not jump when the rows arrive. */
export function LibrariesSkeleton() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10" aria-busy="true">
      <h1 className="font-serif text-3xl font-semibold tracking-tight">Libraries</h1>
      <p role="status" className="mt-2 text-muted-foreground">
        Loading libraries…
      </p>
      <ul aria-hidden="true" className="mt-6 animate-pulse divide-y divide-border">
        {widths.map((w) => (
          <li
            key={w}
            className="flex flex-col gap-3 px-3 py-4 md:flex-row md:items-center md:gap-6"
          >
            <span className={`h-4 rounded bg-secondary ${w}`} />
            <span className="h-6 w-64 max-w-full rounded bg-secondary" />
            <span className="h-4 w-20 rounded bg-secondary md:ml-auto" />
          </li>
        ))}
      </ul>
    </main>
  );
}
