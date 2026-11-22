import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import { JobsPage, jobsQueryOptions, parseJobsView } from "@/features/libraries";

export const Route = createFileRoute("/_app/jobs")({
  validateSearch: parseJobsView,
  loaderDeps: ({ search }) => search,
  loader: ({ context, deps }) =>
    context.queryClient.ensureInfiniteQueryData(jobsQueryOptions(deps)),
  errorComponent: (props) => <RouteError {...props} wide />,
  component: JobsPage,
});
