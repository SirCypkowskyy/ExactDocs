import type { QueryClient } from "@tanstack/react-query";
import { createRouter, type RouterHistory } from "@tanstack/react-router";
import { NotFound, Pending, RouteError } from "@/features/auth";
import { routeTree } from "@/routeTree.gen";
import { stringifySearch } from "@/shared/ui/data-table/table-search";

export interface RouterContext {
  queryClient: QueryClient;
}

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    ...(history && { history }),
    context: { queryClient },
    // A table's facets stay `state=failed,queued` after the route validates them into lists.
    stringifySearch,
    defaultPreload: "intent",
    // TanStack Query owns caching; the router only triggers loaders.
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
    // A move to another page cross-fades the sheet (styles.css, `page`); a change of search or
    // hash on the same page (typing a query, opening an article) does not. Off under reduced motion.
    defaultViewTransition: { types: ({ pathChanged }) => (pathChanged ? ["page"] : false) },
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
