import { createFileRoute } from "@tanstack/react-router";
import { NotFound, RouteError, useSession } from "@/features/auth";
import { OverviewPage, OverviewSkeleton, parseOverviewView } from "@/features/overview";

// Operators only: anyone else finds nothing here (and the API answers them 403). The URL holds
// the charts' range (`days`). Its blocks load on their own, each with a skeleton in place; the
// skeleton below covers the page's own chunk (Recharts is a further chunk, loaded by the charts).
export const Route = createFileRoute("/_app/overview")({
  validateSearch: parseOverviewView,
  pendingMs: 150,
  pendingComponent: OverviewSkeleton,
  errorComponent: (props) => <RouteError {...props} wide />,
  component: function Overview() {
    if (useSession()?.account?.role !== "admin") return <NotFound />;
    return <OverviewPage />;
  },
});
