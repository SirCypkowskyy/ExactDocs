import { createFileRoute } from "@tanstack/react-router";
import { AiPage, parseUsageView } from "@/features/ai";
import { NotFound, useSession } from "@/features/auth";

// Operators only: anyone else finds nothing here (and the API answers them 403). The URL holds
// the usage table's view (filters, sort, page, size).
export const Route = createFileRoute("/_app/ai")({
  validateSearch: parseUsageView,
  component: function Ai() {
    if (useSession()?.account?.role !== "admin") return <NotFound />;
    return <AiPage />;
  },
});
