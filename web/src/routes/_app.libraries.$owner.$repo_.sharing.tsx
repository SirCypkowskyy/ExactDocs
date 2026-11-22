import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import { LibraryNotFound, libraryQueryOptions } from "@/features/browse";
import { parseSharingView, SharingPage } from "@/features/sharing";
import { HttpError } from "@/shared/lib/http";

export const Route = createFileRoute("/_app/libraries/$owner/$repo_/sharing")({
  // The grants table's view (filter, kind, role, sort), so a reload or a shared link keeps it.
  validateSearch: parseSharingView,
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(libraryQueryOptions(params.owner, params.repo)),
  errorComponent: function SharingError(props) {
    const { owner, repo } = Route.useParams();
    if (props.error instanceof HttpError && props.error.status === 404) {
      return <LibraryNotFound owner={owner} repo={repo} />;
    }
    return <RouteError {...props} wide />;
  },
  component: function Sharing() {
    const { owner, repo } = Route.useParams();
    const { data } = useSuspenseQuery(libraryQueryOptions(owner, repo));
    const view = Route.useSearch();
    const navigate = Route.useNavigate();
    return (
      <SharingPage
        owner={owner}
        repo={repo}
        libraryId={data.id}
        title={data.title}
        view={view}
        onView={(next) => void navigate({ search: { ...next }, replace: true })}
      />
    );
  },
});
