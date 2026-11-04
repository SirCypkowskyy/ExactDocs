import type { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { NotFound, Pending, RouteError } from "@/features/auth";
import { routeTree } from "@/routeTree.gen";
import { AppShell } from "./app-shell";

export interface RouterContext {
  queryClient: QueryClient;
}

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: "intent",
    // TanStack Query owns caching; the router only triggers loaders.
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
    InnerWrap: AppShell,
    defaultPendingComponent: Pending,
    defaultErrorComponent: RouteError,
    defaultNotFoundComponent: NotFound,
  });
}

export type AppRouter = ReturnType<typeof createAppRouter>;

declare module "@tanstack/react-router" {
  interface Register {
    router: AppRouter;
  }
}
