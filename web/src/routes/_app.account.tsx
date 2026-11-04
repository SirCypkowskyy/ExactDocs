import { createFileRoute, useRouter } from "@tanstack/react-router";
import { AccountPanel } from "@/features/auth";

export const Route = createFileRoute("/_app/account")({
  component: function Account() {
    const router = useRouter();
    return <AccountPanel onSignedOut={() => router.navigate({ to: "/sign-in", replace: true })} />;
  },
});
