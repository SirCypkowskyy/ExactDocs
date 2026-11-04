import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import { BrowsePage, libraryQueryOptions, parseSearch } from "@/features/browse";

export const Route = createFileRoute("/_app/libraries/$owner/$repo")({
  validateSearch: parseSearch,
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(libraryQueryOptions(params.owner, params.repo)),
  errorComponent: (props) => <RouteError {...props} wide />,
  component: function Browse() {
    const { owner, repo } = Route.useParams();
    const search = Route.useSearch();
    return <BrowsePage owner={owner} repo={repo} search={search} />;
  },
});
