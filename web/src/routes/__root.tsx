import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import type { RouterContext } from "@/app/router";

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
});

function RootLayout() {
  return (
    <div className="min-h-dvh">
      <header className="border-b px-6 py-3 font-semibold">ExactDocs</header>
      <Outlet />
    </div>
  );
}
