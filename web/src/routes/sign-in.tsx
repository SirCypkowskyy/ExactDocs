import { createFileRoute, redirect, useRouter } from "@tanstack/react-router";
import { guard, SignInPage, safeNext } from "@/features/auth";

export const Route = createFileRoute("/sign-in")({
  // Only same-origin paths survive; anything else is dropped rather than followed.
  validateSearch: (search): { next?: string | undefined } => ({ next: safeNext(search.next) }),
  beforeLoad: async ({ context, location }) => {
    const target = await guard(context.queryClient, "sign-in", location.href);
    if (target) throw redirect(target);
  },
  component: function SignIn() {
    const router = useRouter();
    const { next } = Route.useSearch();
    return <SignInPage next={next} onSignedIn={(to) => router.history.push(to)} />;
  },
});
