import { createFileRoute, useRouter } from "@tanstack/react-router";
import { AccountPanel } from "@/features/auth";
import { parseTokensView, TokensSection } from "@/features/tokens";

export const Route = createFileRoute("/_app/account")({
  validateSearch: parseTokensView,
  component: function Account() {
    const router = useRouter();
    const view = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <AccountPanel onSignedOut={() => router.navigate({ to: "/sign-in", replace: true })}>
        {/* The URL holds the token list's search and sort, so a reload keeps them. */}
        <TokensSection
          view={view}
          onView={(next) => void navigate({ search: { ...next }, replace: true })}
        />
      </AccountPanel>
    );
  },
});
