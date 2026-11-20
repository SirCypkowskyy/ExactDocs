import type { QueryClient } from "@tanstack/react-query";
import { createRouter, type RouterHistory } from "@tanstack/react-router";
import { NotFound, Pending, RouteError } from "@/features/auth";
import { routeTree } from "@/routeTree.gen";

export interface RouterContext {
  queryClient: QueryClient;
}

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    ...(history && { history }),
    context: { queryClient },
    defaultPreload: "intent",
    // TanStack Query owns caching; the router only triggers loaders.
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
    // Route changes cross-fade the sheet (styles.css, `page`); skipped under reduced motion there.
    defaultViewTransition: true,
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
