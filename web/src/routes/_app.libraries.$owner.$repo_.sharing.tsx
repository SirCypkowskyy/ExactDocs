import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import { LibraryNotFound, libraryQueryOptions } from "@/features/browse";
import {
  grantsPageQueryOptions,
  parseSharingView,
  SharingPage,
  SharingSkeleton,
  sharingSummaryQueryOptions,
} from "@/features/sharing";
import { HttpError } from "@/shared/lib/http";

export const Route = createFileRoute("/_app/libraries/$owner/$repo_/sharing")({
  // The grants table's view (filter, kinds, roles, sort, page, size), so a reload or a shared link
  // keeps it.
  validateSearch: parseSharingView,
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps }) => {
    // Asked for together with the library; a refusal (not an admin) shows on the page, not here.
    void context.queryClient.prefetchQuery(sharingSummaryQueryOptions(params.owner, params.repo));
    void context.queryClient.prefetchQuery(grantsPageQueryOptions(params.owner, params.repo, deps));
    return context.queryClient.ensureQueryData(libraryQueryOptions(params.owner, params.repo));
  },
  pendingMs: 150,
  pendingComponent: SharingSkeleton,
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
    return (
      <SharingPage
        owner={owner}
        repo={repo}
        libraryId={data.id}
        title={data.title}
        logo={data.logo}
      />
    );
  },
});
