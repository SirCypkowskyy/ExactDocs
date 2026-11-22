import { createFileRoute } from "@tanstack/react-router";
import { NotFound, useSession } from "@/features/auth";
import { parseUsersView, UsersPage } from "@/features/users";

// Operators only: anyone else finds nothing here (and the API answers them 403).
export const Route = createFileRoute("/_app/users")({
  validateSearch: parseUsersView,
  component: function Users() {
    const account = useSession()?.account;
    const view = Route.useSearch();
    const navigate = Route.useNavigate();
    if (account?.role !== "admin") return <NotFound />;
    // The URL holds the view, so a reload or a shared link shows the same list.
    return (
      <UsersPage
        currentUserId={account.id}
        view={view}
        onView={(next) => void navigate({ search: { ...next }, replace: true })}
      />
    );
  },
});
