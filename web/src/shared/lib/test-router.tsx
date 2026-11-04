import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import type { ComponentType } from "react";

/** A memory router with one page at `/` and a stub at each other path, for Link-bearing components. */
export function TestRouter({
  pages,
  start = "/",
}: {
  pages: Record<string, ComponentType>;
  start?: string;
}) {
  const root = createRootRoute({ component: Outlet });
  const routes = Object.entries(pages).map(([path, component]) =>
    createRoute({ getParentRoute: () => root, path, component: component as never }),
  );
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({ initialEntries: [start] }),
  });
  return <RouterProvider router={router as never} />;
}
