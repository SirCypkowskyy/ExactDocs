import { createFileRoute, redirect, useRouter } from "@tanstack/react-router";
import { guard, SignInPage, safeNext, useSession } from "@/features/auth";

export const Route = createFileRoute("/sign-in")({
  // Only same-origin paths survive; anything else is dropped rather than followed.
  validateSearch: (search): { next?: string | undefined; error?: string | undefined } => ({
    next: safeNext(search.next),
    // A refused sign-in through an identity provider comes back with its code only.
    error: typeof search.error === "string" ? search.error : undefined,
  }),
  beforeLoad: async ({ context, location }) => {
    const target = await guard(context.queryClient, "sign-in", location.href);
    if (target) throw redirect(target);
  },
  component: function SignIn() {
    const router = useRouter();
    const { next, error } = Route.useSearch();
    const providers = useSession()?.providers;
    return (
      <SignInPage
        next={next}
        error={error}
        providers={providers}
        onSignedIn={(to) => router.navigate({ to, replace: true })}
      />
    );
  },
});
