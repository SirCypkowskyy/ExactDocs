import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import {
  LibrariesPage,
  LibrariesSkeleton,
  librariesQueryOptions,
  parseListView,
} from "@/features/libraries";

export const Route = createFileRoute("/_app/")({
  validateSearch: parseListView,
  loaderDeps: ({ search }) => search,
  loader: ({ context, deps }) =>
    context.queryClient.ensureInfiniteQueryData(librariesQueryOptions(deps)),
  pendingMs: 150,
  pendingComponent: LibrariesSkeleton,
  errorComponent: (props) => <RouteError {...props} wide />,
  component: LibrariesPage,
});
