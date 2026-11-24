import { createFileRoute } from "@tanstack/react-router";
import { NotFound, useSession } from "@/features/auth";
import { parseUsersView, UsersPage } from "@/features/users";

// Operators only: anyone else finds nothing here (and the API answers them 403).
export const Route = createFileRoute("/_app/users")({
  // The URL holds the table's view (search, filters, sort, page, size), so a reload or a shared
  // link shows the same rows.
  validateSearch: parseUsersView,
  component: function Users() {
    const session = useSession();
    const account = session?.account;
    if (account?.role !== "admin") return <NotFound />;
    // The sign-in filter offers the providers configured now (the session lists them).
    return <UsersPage currentUserId={account.id} providers={session?.providers} />;
  },
});
