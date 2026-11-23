import { createFileRoute } from "@tanstack/react-router";
import { LibraryAccessLogPage, parseLibraryAccessLogView } from "@/features/access-log";

// Library admins and operators; the API answers anyone else 403 (or 404 without any role).
export const Route = createFileRoute("/_app/libraries/$owner/$repo_/access-log")({
  validateSearch: parseLibraryAccessLogView,
  component: function LibraryAccessLog() {
    const { owner, repo } = Route.useParams();
    const view = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <LibraryAccessLogPage
        owner={owner}
        repo={repo}
        view={view}
        onView={(next) => void navigate({ search: { change: next.change }, replace: true })}
      />
    );
  },
});
