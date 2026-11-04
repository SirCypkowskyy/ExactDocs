import { Link, useRouter } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { SignOutButton, useSession } from "@/features/auth";

const navLink =
  "rounded-md px-2 py-2 text-sm font-medium text-muted-foreground outline-none transition-colors duration-150 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:text-foreground aria-[current=page]:shadow-[inset_0_-2px_0_var(--mark)] sm:px-3";

/** Header and frame for signed-in pages. The auth pages bring their own frame. */
export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const session = useSession();

  return (
    <div className="min-h-dvh">
      <header className="flex items-center gap-x-1 border-b border-border px-4 py-2 sm:gap-x-2 sm:px-6">
        <Link to="/" className="mr-2 font-serif text-lg font-semibold tracking-tight sm:mr-4">
          ExactDocs
        </Link>
        <nav aria-label="Main" className="flex gap-0.5">
          <Link to="/" activeOptions={{ exact: true }} className={navLink}>
            Libraries
          </Link>
          <Link to="/account" className={navLink}>
            Account
          </Link>
        </nav>
        {/* On a phone the Account page holds sign-out, which keeps this to one row. */}
        <div className="ml-auto hidden items-center gap-3 sm:flex">
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
