import { ShieldCheck, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Avatar } from "@/shared/ui/avatar";
import { Badge } from "@/shared/ui/badge";
import { Page, PageHeader } from "@/shared/ui/page";
import type { HelpTopic } from "@/shared/ui/page-help";
import { useSession } from "../hooks/use-session";
import { messages, roleName } from "../messages";
import { SignOutButton } from "./sign-out-button";

export function AccountPanel({
  onSignedOut,
  help,
  children,
}: {
  onSignedOut: () => void;
  /** The page's tour, composed by the route like the sections. */
  help?: HelpTopic;
  /** Sections composed by the route (the auth slice cannot import other features). */
  children?: ReactNode;
}) {
  const session = useSession();
  const account = session?.account;
  const t = useMessages(messages);
  const heading = usePageTitle(t.account.title);
  return (
    <Page>
      <PageHeader
        title={t.account.title}
        icon={<UserRound />}
        headingRef={heading}
        help={help}
        description={t.account.description}
      />
      <div className="grid items-start gap-10 lg:grid-cols-[18rem_minmax(0,1fr)] lg:gap-12">
        <section
          aria-labelledby="identity-heading"
          className="rounded-lg border border-border bg-raised p-5"
        >
          <h2 id="identity-heading" className="flex items-center gap-2 text-section font-semibold">
            <UserRound aria-hidden="true" className="size-4 text-muted-foreground" />
            {t.account.signedInAs}
          </h2>
          <dl className="mt-4 grid grid-cols-[5.5rem_minmax(0,1fr)] items-baseline gap-y-3 text-body">
            <dt className="text-muted-foreground">{t.account.username}</dt>
            <dd className="flex min-w-0 items-center gap-2 font-medium">
              {account && <Avatar name={account.username} />}
              <span className="min-w-0 [overflow-wrap:anywhere]">{account?.username}</span>
            </dd>
            <dt className="text-muted-foreground">{t.account.role}</dt>
            <dd>
              <Badge tone={account?.role === "admin" ? "route" : "neutral"} className="capitalize">
                {account?.role === "admin" ? (
                  <ShieldCheck aria-hidden="true" className="size-3" />
                ) : (
                  <UserRound aria-hidden="true" className="size-3" />
                )}
                {roleName(t.roles, account?.role)}
              </Badge>
            </dd>
            {session?.source === "cloudflare_access" && (
              <>
                <dt className="text-muted-foreground">{t.account.signedIn}</dt>
                <dd className="font-medium">{t.account.throughAccess}</dd>
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
