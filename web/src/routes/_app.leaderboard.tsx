import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import {
  LeaderboardPage,
  LeaderboardSkeleton,
  parseLeaderboardView,
  statsSettingsQueryOptions,
} from "@/features/leaderboard";

// Everyone signed in: the libraries board is always there; the people board only while the
// operator turned it on (`GET /stats/settings`). The URL holds the board (subject, metric,
// period) and the view of the table below it. The loader waits for the settings only, so a
// switch of board never shows the skeleton: the columns move from where they are.
export const Route = createFileRoute("/_app/leaderboard")({
  validateSearch: parseLeaderboardView,
  loader: ({ context }) => context.queryClient.ensureQueryData(statsSettingsQueryOptions()),
  pendingMs: 150,
  pendingComponent: LeaderboardSkeleton,
  errorComponent: (props) => <RouteError {...props} wide />,
  component: LeaderboardPage,
});
