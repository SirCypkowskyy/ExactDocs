import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import {
  BrowsePage,
  LibraryNotFound,
  libraryQueryOptions,
  parseSearch,
  type SearchSlots,
} from "@/features/browse";
import { SearchBox, SearchResults } from "@/features/search";
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
    // The search slice and the browse slice never import each other: the route joins them.
    const slots: SearchSlots = {
      box: (v) => (
        <SearchBox
          ctx={{ owner, repo, q: search.q, tags: search.tags, match: search.match ?? "any", ...v }}
        />
      ),
      results: (v) => (
        <SearchResults
          ctx={{ owner, repo, q: search.q, tags: search.tags, match: search.match ?? "any", ...v }}
        />
      ),
    };
    return <BrowsePage owner={owner} repo={repo} search={search} slots={slots} />;
  },
});
