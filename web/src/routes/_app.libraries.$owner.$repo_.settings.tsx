import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import { LibraryNotFound, libraryQueryOptions } from "@/features/browse";
import { ImportProgress, JobLine, SelectionPreview } from "@/features/libraries";
import { LibrarySettingsPage, parseVersionsView } from "@/features/library-settings";
import { HttpError } from "@/shared/lib/http";

// The job and preview views come from `libraries`, the page from `library-settings`: a route is where slices meet.
const jobs = { Import: ImportProgress, Line: JobLine, Preview: SelectionPreview };

export const Route = createFileRoute("/_app/libraries/$owner/$repo_/settings")({
  // The versions table's view (filter, kind, sort), so a reload or a shared link keeps it.
  validateSearch: parseVersionsView,
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(libraryQueryOptions(params.owner, params.repo)),
  errorComponent: function SettingsError(props) {
    const { owner, repo } = Route.useParams();
    if (props.error instanceof HttpError && props.error.status === 404) {
      return <LibraryNotFound owner={owner} repo={repo} />;
    }
    return <RouteError {...props} wide />;
  },
  component: function Settings() {
    const { owner, repo } = Route.useParams();
    const { data } = useSuspenseQuery(libraryQueryOptions(owner, repo));
    return <LibrarySettingsPage owner={owner} repo={repo} library={data} jobs={jobs} />;
  },
});
