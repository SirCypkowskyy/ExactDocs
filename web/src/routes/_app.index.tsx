import { createFileRoute } from "@tanstack/react-router";
import { LibrariesPage, LibrariesSkeleton, librariesQueryOptions } from "@/features/libraries";

export const Route = createFileRoute("/_app/")({
  loader: ({ context }) => context.queryClient.ensureQueryData(librariesQueryOptions()),
  pendingMs: 150,
  pendingComponent: LibrariesSkeleton,
  component: LibrariesPage,
});
