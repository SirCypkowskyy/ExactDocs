import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { LibraryAccessLogPage, parseLibraryAccessLogView } from "@/features/access-log";
import { libraryQueryOptions } from "@/features/browse";

// Library admins and operators; the API answers anyone else 403 (or 404 without any role). The
// URL holds the view (changes, page, size).
export const Route = createFileRoute("/_app/libraries/$owner/$repo_/access-log")({
  validateSearch: parseLibraryAccessLogView,
  component: function LibraryAccessLog() {
    const { owner, repo } = Route.useParams();
    // The header's logo from the library this browser already loaded (the library or sharing
    // page links here); never a request of its own: without it the header shows the generic mark.
    const { data } = useQuery({ ...libraryQueryOptions(owner, repo), enabled: false });
    return <LibraryAccessLogPage owner={owner} repo={repo} logo={data?.logo} />;
  },
});
