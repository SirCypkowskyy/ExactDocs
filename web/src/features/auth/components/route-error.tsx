import { Navigate, useLocation } from "@tanstack/react-router";
import { HttpError } from "@/shared/lib/http";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Button } from "@/shared/ui/button";

/**
 * Error screen for every route. A request refused for want of a session (it expired after the
 * guard let the page through) goes to sign-in and comes back; anything else gets a retry.
 */
export function RouteError({
  error,
  reset,
  wide = false,
}: {
  error: unknown;
  reset: () => void;
  /** Sit at the left edge of an app page instead of centred like the auth screens. */
  wide?: boolean;
}) {
  const href = useLocation({ select: (l) => l.href });
  // 4xx details are written for people by the API; everything else gets the fixed sentence.
  const answered = error instanceof HttpError && error.status < 500 && Boolean(error.code);
  const title = answered ? "Something went wrong" : "Can't reach the server";
  const heading = usePageTitle(title);
  if (error instanceof HttpError && error.status === 401) {
    return <Navigate to="/sign-in" search={{ next: href }} replace />;
  }
  if (error instanceof HttpError && error.code === "setup_required") {
    return <Navigate to="/setup" replace />;
  }
  const detail =
    error instanceof HttpError && answered
      ? error.message
      : "ExactDocs didn't answer. Check that it is running, then try again.";
  return (
    <main
      className={
        wide
          ? "mx-auto flex max-w-5xl flex-col items-start gap-4 px-4 py-8 sm:px-6 sm:py-10"
          : "mx-auto flex max-w-md flex-col items-start gap-4 px-6 py-20"
      }
    >
      <h1
        ref={heading}
        tabIndex={-1}
        className="font-serif text-3xl font-semibold tracking-tight outline-none"
      >
        {title}
      </h1>
      <div role="alert" className="text-muted-foreground">
        <p>{detail}</p>
      </div>
      <Button onClick={reset}>Try again</Button>
    </main>
  );
}
