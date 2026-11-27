import { createFileRoute } from "@tanstack/react-router";
import { NotFound, useSession } from "@/features/auth";
import { RoleRulesPage } from "@/features/users";

// The role rules, a view of the users page: operators only (the API answers anyone else 403).
export const Route = createFileRoute("/_app/users_/rules")({
  component: function RoleRules() {
    const account = useSession()?.account;
    if (account?.role !== "admin") return <NotFound />;
    return <RoleRulesPage />;
  },
});
