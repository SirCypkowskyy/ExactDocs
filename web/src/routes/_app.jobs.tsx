import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import { JobsPage, JobsSkeleton, jobsPageQueryOptions, parseJobsView } from "@/features/libraries";

export const Route = createFileRoute("/_app/jobs")({
  validateSearch: parseJobsView,
  loaderDeps: ({ search }) => search,
  loader: ({ context, deps }) => context.queryClient.ensureQueryData(jobsPageQueryOptions(deps)),
  pendingMs: 150,
  pendingComponent: JobsSkeleton,
  errorComponent: (props) => <RouteError {...props} wide />,
  component: JobsPage,
});
