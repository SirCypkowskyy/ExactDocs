import { createFileRoute } from "@tanstack/react-router";
import { AccessLogPage, parseAccessLogView } from "@/features/access-log";
import { NotFound, useSession } from "@/features/auth";

// Operators only: anyone else finds nothing here (and the API answers them 403). The URL holds
// the view (changes, library, page, size), so a reload or a shared link shows the same list.
export const Route = createFileRoute("/_app/access-log")({
  validateSearch: parseAccessLogView,
  component: function AccessLog() {
    const account = useSession()?.account;
    if (account?.role !== "admin") return <NotFound />;
    return <AccessLogPage />;
  },
});
