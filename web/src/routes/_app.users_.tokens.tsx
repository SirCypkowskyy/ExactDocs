import { createFileRoute } from "@tanstack/react-router";
import { NotFound, useSession } from "@/features/auth";
import { AllTokensPage, parseAllTokensView } from "@/features/users";

// Every account's API tokens, a view of the users page: operators only (the API answers anyone
// else 403). The URL holds the table's view, so a reload or a shared link shows the same rows.
export const Route = createFileRoute("/_app/users_/tokens")({
  validateSearch: parseAllTokensView,
  component: function AllTokens() {
    const account = useSession()?.account;
    if (account?.role !== "admin") return <NotFound />;
    return <AllTokensPage />;
  },
});
