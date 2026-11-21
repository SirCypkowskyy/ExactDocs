import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useLocation } from "@tanstack/react-router";
import { MapPinOff } from "lucide-react";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { buttonVariants } from "@/shared/ui/button";
import { StatusScreen } from "@/shared/ui/status-screen";
import { sessionQueryOptions } from "../api/session-query";
import { resolveGuard } from "../model/session";
import { Pending } from "./pending";

/** An unknown address still obeys the gate: setup first, then sign-in, and only then "not found". */
export function NotFound() {
  const href = useLocation({ select: (l) => l.href });
  const { data } = useQuery({ ...sessionQueryOptions(), staleTime: 0 });
  const heading = usePageTitle("Page not found");
  if (!data) return <Pending />;
  const target = data.state === "signed_in" ? null : resolveGuard(data.state, "app", href);
  if (target) return <Navigate {...target} replace />;
  return (
    <StatusScreen
      icon={<MapPinOff aria-hidden="true" />}
      title="Page not found"
      headingRef={heading}
      actions={
        <Link to="/" className={buttonVariants()}>
          Back to libraries
        </Link>
      }
    >
      There is nothing at this address.
    </StatusScreen>
  );
}
