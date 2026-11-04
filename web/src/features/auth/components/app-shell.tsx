import { Link, useLocation, useRouter } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useSession } from "../hooks/use-session";
import { SignOutButton } from "./sign-out-button";

const navLink =
  "rounded-md px-2 py-2 text-sm font-medium text-muted-foreground outline-none transition-colors duration-150 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:text-foreground aria-[current=page]:shadow-[inset_0_-2px_0_var(--mark)] sm:px-3";

/** Header and frame for signed-in pages. The auth pages bring their own frame. */
export function AppShell({ children, search }: { children: ReactNode; search?: ReactNode }) {
  const router = useRouter();
  const session = useSession();
  // Libraries owns `/` and everything under `/libraries`, so the tab stays lit on the add screen.
  const inLibraries = useLocation({
    select: (l) => l.pathname === "/" || l.pathname.startsWith("/libraries"),
  });

  return (
    <div className="min-h-dvh">
      <header className="flex flex-wrap items-center gap-x-1 border-b border-border px-4 py-2 sm:gap-x-2 sm:px-6">
        <Link to="/" className="mr-2 font-serif text-lg font-semibold tracking-tight sm:mr-4">
          ExactDocs
        </Link>
        <nav aria-label="Main" className="flex gap-0.5">
          <Link
            to="/"
            activeOptions={{ exact: true }}
            className={navLink}
            {...(inLibraries && { "aria-current": "page" as const })}
          >
            Libraries
          </Link>
          <Link to="/account" className={navLink}>
            Account
          </Link>
        </nav>
        {/* A phone gets the box on its own row; from sm up it sits between the tabs and the account. */}
        {search && (
          <div className="order-last flex w-full sm:order-none sm:ml-auto sm:w-auto sm:flex-1 sm:justify-end">
            {search}
          </div>
        )}
        {/* On a phone the Account page holds sign-out, which keeps this to one row. */}
        <div className={`${search ? "" : "ml-auto "}hidden items-center gap-3 sm:flex`}>
          <span className="max-w-[12rem] truncate text-sm text-muted-foreground">
            {session?.account?.username}
          </span>
          <SignOutButton onSignedOut={() => router.navigate({ to: "/sign-in", replace: true })} />
        </div>
      </header>
      {children}
    </div>
  );
}
