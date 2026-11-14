import { createFileRoute } from "@tanstack/react-router";
import { NotFound, useSession } from "@/features/auth";
import { UsersPage } from "@/features/users";

// Operators only: anyone else finds nothing here (and the API answers them 403).
export const Route = createFileRoute("/_app/users")({
  component: function Users() {
    const account = useSession()?.account;
    if (account?.role !== "admin") return <NotFound />;
    return <UsersPage currentUserId={account.id} />;
  },
});
