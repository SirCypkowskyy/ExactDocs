import { Link, useLocation, useRouter } from "@tanstack/react-router";
import { Search } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/shared/lib/utils";
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
  const onSearch = useLocation({ select: (l) => l.pathname === "/search" });

  return (
    <div className="min-h-dvh">
      <header className="flex flex-wrap items-center gap-y-2 gap-x-1 border-b border-border px-4 py-2 sm:gap-x-2 sm:px-6">
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
        {search && (
          <>
            {/* A phone gets a 44px door to /search (its box sits at the top of that page); from sm up the box lives here. */}
            <Link
              to="/search"
              // On /search itself the door keeps the query instead of wiping it.
              search={onSearch ? true : {}}
              aria-label="Search all libraries"
              className="ml-auto inline-flex size-11 items-center justify-center rounded-md text-muted-foreground outline-none transition-[color,transform] duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.95] sm:hidden [@media(hover:hover)]:hover:text-foreground"
            >
              <Search aria-hidden="true" className="size-5" />
            </Link>
            <div className="hidden sm:ml-auto sm:flex sm:flex-1 sm:justify-end">{search}</div>
          </>
        )}
        {/* On a phone the Account page holds sign-out, which keeps this to one row. */}
        <div className={cn("hidden items-center gap-3 sm:flex", !search && "ml-auto")}>
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
