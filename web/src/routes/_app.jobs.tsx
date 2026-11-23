import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import { JobsPage, jobsPageQueryOptions, parseJobsView } from "@/features/libraries";

export const Route = createFileRoute("/_app/jobs")({
  validateSearch: parseJobsView,
  loaderDeps: ({ search }) => search,
  loader: ({ context, deps }) => context.queryClient.ensureQueryData(jobsPageQueryOptions(deps)),
  errorComponent: (props) => <RouteError {...props} wide />,
  component: JobsPage,
});
