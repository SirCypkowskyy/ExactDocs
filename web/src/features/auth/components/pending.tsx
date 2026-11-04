/** First paint of a cold load: just the name, and only if the session check is slow enough to notice. */
export function Pending() {
  return (
    <main className="pending-in grid min-h-dvh place-items-center">
      <p role="status" className="font-serif text-xl text-muted-foreground">
        <span className="sr-only">Loading </span>
        ExactDocs
      </p>
    </main>
  );
}
