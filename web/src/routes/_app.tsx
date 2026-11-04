import { createFileRoute, Navigate, Outlet, redirect, useLocation } from "@tanstack/react-router";
import { AppShell } from "@/app/app-shell";
import { guard, resolveGuard, useSession } from "@/features/auth";

// Everything behind sign-in lives under this pathless layout.
export const Route = createFileRoute("/_app")({
  beforeLoad: async ({ context, location }) => {
    const target = await guard(context.queryClient, "app", location.href);
    if (target) throw redirect(target);
  },
  component: function AppLayout() {
    const session = useSession();
    const href = useLocation({ select: (l) => l.href });
    const pathname = useLocation({ select: (l) => l.pathname });
    // The guard only runs on navigation; a session that ends while the page is open lands here.
    const target = session ? resolveGuard(session.state, "app", href) : null;
    // Mid-transition this layout still renders once at the destination; do not redirect twice.
    if (target && target.to !== pathname) return <Navigate {...target} replace />;
    return (
      <AppShell>
        <Outlet />
      </AppShell>
    );
  },
});
