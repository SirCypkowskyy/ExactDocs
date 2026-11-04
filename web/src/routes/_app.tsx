import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { guard } from "@/features/auth";

// Everything behind sign-in lives under this pathless layout.
export const Route = createFileRoute("/_app")({
  beforeLoad: async ({ context, location }) => {
    const target = await guard(context.queryClient, "app", location.href);
    if (target) throw redirect(target);
  },
  component: Outlet,
});
