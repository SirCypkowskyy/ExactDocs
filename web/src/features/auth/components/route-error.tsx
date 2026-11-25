import { Navigate, useLocation } from "@tanstack/react-router";
import { CloudOff, RotateCcw } from "lucide-react";
import { HttpError } from "@/shared/lib/http";
import { useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Button } from "@/shared/ui/button";
import { StatusScreen } from "@/shared/ui/status-screen";
import { messages } from "../messages";

/**
 * Error screen for every route. A request refused for want of a session (it expired after the
 * guard let the page through) goes to sign-in and comes back; anything else gets a retry.
 */
export function RouteError({
  error,
  reset,
  wide: _wide = false,
}: {
  error: unknown;
  reset: () => void;
  /** Sit at the left edge of an app page instead of centred like the auth screens. */
  wide?: boolean;
}) {
  const href = useLocation({ select: (l) => l.href });
  const t = useMessages(messages);
  // 4xx details are written for people by the API; everything else gets the fixed sentence.
  const answered = error instanceof HttpError && error.status < 500 && Boolean(error.code);
  const title = answered ? t.screens.somethingWrong : t.screens.cantReach;
  const heading = usePageTitle(title);
  if (error instanceof HttpError && error.status === 401) {
    return <Navigate to="/sign-in" search={{ next: href }} replace />;
  }
  if (error instanceof HttpError && error.code === "setup_required") {
    return <Navigate to="/setup" replace />;
  }
  const detail = error instanceof HttpError && answered ? error.message : t.screens.didntAnswer;
  return (
    <StatusScreen
      icon={<CloudOff aria-hidden="true" />}
      title={title}
      headingRef={heading}
      alert
      actions={
        <Button onClick={reset}>
          <RotateCcw aria-hidden="true" data-icon-motion="refresh" />
          {t.screens.tryAgain}
        </Button>
      }
    >
      <p>{detail}</p>
    </StatusScreen>
  );
}
