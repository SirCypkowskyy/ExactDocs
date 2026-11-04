import { Navigate, useLocation } from "@tanstack/react-router";
import { HttpError } from "@/shared/lib/http";
import { Button } from "@/shared/ui/button";

/**
 * Error screen for every route. A request refused for want of a session (it expired after the
 * guard let the page through) goes to sign-in and comes back; anything else gets a retry.
 */
export function RouteError({ error, reset }: { error: unknown; reset: () => void }) {
  const href = useLocation({ select: (l) => l.href });
  if (error instanceof HttpError && error.status === 401) {
    return <Navigate to="/sign-in" search={{ next: href }} replace />;
  }
  if (error instanceof HttpError && error.code === "setup_required") {
    return <Navigate to="/setup" replace />;
  }
  return (
    <main className="mx-auto flex max-w-md flex-col items-start gap-4 px-6 py-20">
      <h1 className="font-serif text-3xl font-semibold tracking-tight">Something went wrong</h1>
      <p role="alert" className="text-muted-foreground">
        {error instanceof HttpError && error.status < 500
          ? error.message
          : "ExactDocs could not load this page. Check that the server is running, then try again."}
      </p>
      <Button onClick={reset}>Try again</Button>
    </main>
  );
}
