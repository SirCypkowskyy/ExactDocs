import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import { BrowsePage, LibraryNotFound, libraryQueryOptions, parseSearch } from "@/features/browse";
import { HttpError } from "@/shared/lib/http";

export const Route = createFileRoute("/_app/libraries/$owner/$repo")({
  validateSearch: parseSearch,
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(libraryQueryOptions(params.owner, params.repo)),
  errorComponent: function BrowseError(props) {
    const { owner, repo } = Route.useParams();
    if (props.error instanceof HttpError && props.error.status === 404) {
      return <LibraryNotFound owner={owner} repo={repo} />;
    }
    return <RouteError {...props} wide />;
  },
  component: function Browse() {
    const { owner, repo } = Route.useParams();
    const search = Route.useSearch();
    return <BrowsePage owner={owner} repo={repo} search={search} />;
  },
});
