import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
  RouterProvider,
} from "@tanstack/react-router";
import type { ComponentType } from "react";

/**
 * A memory router with one page at `/` and a stub at each other path, for Link-bearing components.
 * Pass `history` to step back and forth in a test; it then decides where the router starts.
 */
export function TestRouter({
  pages,
  start = "/",
  history = createMemoryHistory({ initialEntries: [start] }),
}: {
  pages: Record<string, ComponentType>;
  start?: string;
  history?: RouterHistory;
}) {
  const root = createRootRoute({ component: Outlet });
  const routes = Object.entries(pages).map(([path, component]) =>
    createRoute({ getParentRoute: () => root, path, component: component as never }),
  );
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history,
  });
  return <RouterProvider router={router as never} />;
}
