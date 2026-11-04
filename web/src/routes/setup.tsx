import { createFileRoute, redirect, useRouter } from "@tanstack/react-router";
import { guard, SetupPage } from "@/features/auth";

export const Route = createFileRoute("/setup")({
  beforeLoad: async ({ context, location }) => {
    const target = await guard(context.queryClient, "setup", location.href);
    if (target) throw redirect(target);
  },
  component: function Setup() {
    const router = useRouter();
    return <SetupPage onDone={() => router.navigate({ to: "/", replace: true })} />;
  },
});
