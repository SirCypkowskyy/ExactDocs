import { useQuery } from "@tanstack/react-query";
import { Navigate, useLocation } from "@tanstack/react-router";
import { sessionQueryOptions } from "../api/session-query";
import { resolveGuard } from "../model/session";
import { Pending } from "./pending";

/** An unknown address still obeys the gate: setup first, then sign-in, and only then "not found". */
export function NotFound() {
  const href = useLocation({ select: (l) => l.href });
  const { data } = useQuery({ ...sessionQueryOptions(), staleTime: 0 });
  if (!data) return <Pending />;
  const target = data.state === "signed_in" ? null : resolveGuard(data.state, "app", href);
  if (target) return <Navigate {...target} replace />;
  return (
    <main className="mx-auto max-w-md px-6 py-20">
      <h1 className="font-serif text-3xl font-semibold tracking-tight">Page not found</h1>
      <p className="mt-2 text-muted-foreground">There is nothing at this address.</p>
    </main>
  );
}
