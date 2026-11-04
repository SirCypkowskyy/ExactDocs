import { Link, useRouter } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { SignOutButton, useSession } from "@/features/auth";

const navLink =
  "rounded-md px-3 py-2 text-sm font-medium text-muted-foreground outline-none transition-colors duration-150 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:bg-accent aria-[current=page]:text-foreground";

/** Header for signed-in pages (libraries, settings, sign-out). The auth pages bring their own frame. */
export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const session = useSession();
  if (session?.state !== "signed_in") return <>{children}</>;

  return (
    <div className="min-h-dvh">
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 bg-secondary px-4 py-2 sm:px-6">
        <Link to="/" className="mr-4 font-serif text-lg font-semibold tracking-tight">
          ExactDocs
        </Link>
        <nav aria-label="Main" className="order-last flex w-full gap-1 sm:order-none sm:w-auto">
          <Link to="/" activeOptions={{ exact: true }} className={navLink}>
            Libraries
          </Link>
          <Link to="/settings" className={navLink}>
            Settings
          </Link>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden text-sm text-muted-foreground sm:inline">
            {session.account?.username}
          </span>
          <SignOutButton onSignedOut={() => router.navigate({ to: "/sign-in" })} />
        </div>
      </header>
      {children}
    </div>
  );
}
