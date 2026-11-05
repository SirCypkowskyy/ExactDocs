import type { ReactNode } from "react";
import { usePageTitle } from "@/shared/lib/use-page-title";
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
  const account = useSession()?.account;
  const heading = usePageTitle("Account");
  return (
    <main className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <h1
        ref={heading}
        tabIndex={-1}
        className="font-serif text-3xl font-semibold tracking-tight outline-none"
      >
        Account
      </h1>
      <dl className="mt-8 grid max-w-sm grid-cols-[7rem_1fr] gap-y-4 text-base">
        <dt className="text-muted-foreground">Username</dt>
        <dd className="font-medium break-all">{account?.username}</dd>
        <dt className="text-muted-foreground">Role</dt>
        <dd className="font-medium">{account?.role}</dd>
      </dl>
      {/* The header carries sign-out from sm up; a phone's header hides it, so it sits here,
          above the sections, where a long token list can't push it off the screen. */}
      <div className="mt-6 sm:hidden">
        <SignOutButton onSignedOut={onSignedOut} />
      </div>
      {children}
    </main>
  );
}
