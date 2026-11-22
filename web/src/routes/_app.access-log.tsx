import { createFileRoute } from "@tanstack/react-router";
import { AccessLogPage, parseAccessLogView } from "@/features/access-log";
import { NotFound, useSession } from "@/features/auth";

// Operators only: anyone else finds nothing here (and the API answers them 403).
export const Route = createFileRoute("/_app/access-log")({
  validateSearch: parseAccessLogView,
  component: function AccessLog() {
    const account = useSession()?.account;
    const view = Route.useSearch();
    const navigate = Route.useNavigate();
    if (account?.role !== "admin") return <NotFound />;
    // The URL holds the filter, so a reload or a shared link shows the same list.
    return (
      <AccessLogPage
        view={view}
        onView={(next) => void navigate({ search: { ...next }, replace: true })}
      />
    );
  },
});
