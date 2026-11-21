import type { ReactNode } from "react";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import { Page, PageHeader } from "@/shared/ui/page";
import { pill, pillTone } from "@/shared/ui/recipes";
import { useSession } from "../hooks/use-session";
import { SignOutButton } from "./sign-out-button";

export function AccountPanel({
  onSignedOut,
  children,
}: {
  onSignedOut: () => void;
  /** Sections composed by the route (the auth slice cannot import other features). */
  children?: ReactNode;
}) {
  const session = useSession();
  const account = session?.account;
  const heading = usePageTitle("Account");
  return (
    <Page>
      <PageHeader title="Account" headingRef={heading} />
      <div className="grid items-start gap-10 lg:grid-cols-[18rem_minmax(0,1fr)] lg:gap-12">
        <section
          aria-labelledby="identity-heading"
          className="rounded-lg border border-border bg-raised p-5"
        >
          <h2 id="identity-heading" className="text-section font-semibold">
            Signed in as
          </h2>
          <dl className="mt-4 grid grid-cols-[5.5rem_minmax(0,1fr)] items-baseline gap-y-3 text-body">
            <dt className="text-muted-foreground">Username</dt>
            <dd className="font-medium [overflow-wrap:anywhere]">{account?.username}</dd>
            <dt className="text-muted-foreground">Role</dt>
            <dd>
              <span
                className={cn(pill, account?.role === "admin" ? pillTone.route : pillTone.neutral)}
              >
                {account?.role}
              </span>
            </dd>
            {session?.source === "cloudflare_access" && (
              <>
                <dt className="text-muted-foreground">Signed in</dt>
                <dd className="font-medium">through Cloudflare Access</dd>
              </>
            )}
          </dl>
          {/* The header carries sign-out from sm up; a phone's header hides it, so it sits here,
              above the sections, where a long token list can't push it off the screen. -ml-3
              cancels the ghost button's padding so its label lines up with the labels above. */}
          <div className="mt-4 -ml-3 sm:hidden">
            <SignOutButton onSignedOut={onSignedOut} />
          </div>
        </section>
        <div className="min-w-0">{children}</div>
      </div>
    </Page>
  );
}
