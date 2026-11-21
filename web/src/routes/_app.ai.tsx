import { createFileRoute } from "@tanstack/react-router";
import { AiPage } from "@/features/ai";
import { NotFound, useSession } from "@/features/auth";

// Operators only: anyone else finds nothing here (and the API answers them 403).
export const Route = createFileRoute("/_app/ai")({
  component: function Ai() {
    if (useSession()?.account?.role !== "admin") return <NotFound />;
    return <AiPage />;
  },
});
