import { createFileRoute } from "@tanstack/react-router";
import { LibrariesPage, librariesQueryOptions } from "@/features/libraries";

export const Route = createFileRoute("/")({
  loader: ({ context }) => context.queryClient.ensureQueryData(librariesQueryOptions()),
  component: LibrariesPage,
});
