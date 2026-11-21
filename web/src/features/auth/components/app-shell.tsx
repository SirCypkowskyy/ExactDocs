import { useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useRouter } from "@tanstack/react-router";
import { KeyRound, LogOut, Menu, Search } from "lucide-react";
import { type ReactNode, useState } from "react";
import { toast } from "sonner";
import { cn } from "@/shared/lib/utils";
import { buttonVariants } from "@/shared/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/shared/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/shared/ui/sheet";
import { ThemeSwitch } from "@/shared/ui/theme-switch";
import { Mark } from "@/shared/ui/wordmark";
import { signOut } from "../api/session-query";
import { useSession } from "../hooks/use-session";

/*
 * The app shell, after the free shadcnblocks "Application Shell 3" (top navigation bar, a mobile
 * sheet and a user menu), set in ExactDocs' frame: a tinted band and margin around a white sheet
 * that holds the page. The band never scrolls away on the sheet's account; the sheet is the work.
 */

type NavItem = {
  to: "/" | "/search" | "/playground" | "/ai" | "/users";
  label: string;
  admin?: boolean;
};
const NAV: NavItem[] = [
  { to: "/", label: "Libraries" },
  { to: "/search", label: "Search" },
  { to: "/playground", label: "Playground" },
  // AI providers and accounts are for operators (admins); the API refuses anyone else.
  { to: "/ai", label: "AI", admin: true },
  { to: "/users", label: "Users", admin: true },
];

const bandLink =
  "relative inline-flex h-9 items-center rounded-md px-3 text-body font-medium text-muted-foreground outline-none transition-colors duration-(--dur-fast) hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:text-foreground after:pointer-events-none after:absolute after:inset-x-3 after:-bottom-[7px] after:h-0.5 after:origin-center after:scale-x-0 after:rounded-full after:bg-route after:transition-transform after:duration-(--dur) after:ease-(--ease-out) aria-[current=page]:after:scale-x-100";

function useCurrent() {
  const pathname = useLocation({ select: (l) => l.pathname });
  // Libraries owns `/` and everything under `/libraries`, so the tab stays lit on the add screen.
  return (to: NavItem["to"]) =>
    to === "/" ? pathname === "/" || pathname.startsWith("/libraries") : pathname === to;
}

function useSignOut() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [pending, setPending] = useState(false);
  async function run() {
    if (pending) return;
    setPending(true);
    try {
      await signOut(queryClient);
      router.navigate({ to: "/sign-in", replace: true });
    } catch {
      toast.error("Couldn't sign out. Try again.");
    } finally {
      setPending(false);
    }
  }
  return { pending, run };
}

function initials(name: string): string {
  return name.slice(0, 1).toUpperCase() || "?";
}

function UserMenu() {
  const session = useSession();
  const account = session?.account;
  const { pending, run } = useSignOut();
  if (!account) return null;
  // Cloudflare Access signs this browser in on every request: ending only the ExactDocs session
  // would sign it straight back in. Access's own logout ends both.
  const accessSignOut = session?.source === "cloudflare_access" ? session.sign_out_url : null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={`Account: ${account.username}`}
        className="inline-flex h-11 min-w-0 cursor-pointer items-center gap-2 rounded-md px-1.5 text-body outline-none transition-colors duration-(--dur-fast) hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-accent [@media(pointer:fine)]:h-9 md:pr-2.5"
      >
        <span
          aria-hidden="true"
          className="inline-flex size-7 flex-none items-center justify-center rounded-full bg-secondary text-small font-semibold text-foreground"
        >
          {initials(account.username)}
        </span>
        <span className="hidden max-w-[10rem] truncate font-medium md:inline">
          {account.username}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <span className="block truncate text-body font-medium">{account.username}</span>
          <span className="block text-small text-muted-foreground capitalize">{account.role}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/account">
            <KeyRound aria-hidden="true" />
            Account and API tokens
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {accessSignOut ? (
          <DropdownMenuItem asChild>
            <a href={accessSignOut} title="Signs you out of Cloudflare Access">
              <LogOut aria-hidden="true" />
              Sign out
            </a>
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem
            disabled={pending}
            onSelect={(event) => {
              event.preventDefault();
              void run();
            }}
          >
            <LogOut aria-hidden="true" />
            {pending ? "Signing out…" : "Sign out"}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** The phone's navigation: a sheet from the left with every destination and the account. */
function MobileNav({ items }: { items: NavItem[] }) {
  const [open, setOpen] = useState(false);
  const current = useCurrent();
  const session = useSession();
  const { pending, run } = useSignOut();
  const accessSignOut = session?.source === "cloudflare_access" ? session.sign_out_url : null;
  const row =
    "flex h-11 items-center gap-3 rounded-md px-3 text-section font-medium outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:bg-accent";
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        aria-label="Menu"
        className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "-ml-1.5 md:hidden")}
      >
        <Menu aria-hidden="true" className="size-5!" />
      </SheetTrigger>
      <SheetContent side="left" className="w-[min(20rem,85vw)] gap-0 p-0">
        <div className="flex h-13 items-center gap-2 px-4">
          <Mark />
          <SheetTitle className="text-section font-semibold">ExactDocs</SheetTitle>
          <SheetDescription className="sr-only">Pages and your account</SheetDescription>
        </div>
        <nav aria-label="Main" className="flex flex-col gap-0.5 px-2 py-2">
          {items.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              onClick={() => setOpen(false)}
              className={row}
              {...(current(item.to) && { "aria-current": "page" as const })}
            >
              {item.label}
            </Link>
          ))}
          <Link
            to="/account"
            onClick={() => setOpen(false)}
            className={row}
            activeProps={{ "aria-current": "page" }}
          >
            Account and API tokens
          </Link>
        </nav>
        <div className="mt-auto border-t border-border px-2 py-2">
          {accessSignOut ? (
            <a href={accessSignOut} className={row}>
              <LogOut aria-hidden="true" className="size-4" />
              Sign out
            </a>
          ) : (
            <button
              type="button"
              className={cn(row, "w-full cursor-pointer")}
              aria-busy={pending}
              onClick={() => void run()}
            >
              <LogOut aria-hidden="true" className="size-4" />
              {pending ? "Signing out…" : "Sign out"}
            </button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

/** Header band and the sheet for signed-in pages. The auth pages bring their own frame. */
export function AppShell({ children, search }: { children: ReactNode; search?: ReactNode }) {
  const session = useSession();
  const current = useCurrent();
  const onSearch = useLocation({ select: (l) => l.pathname === "/search" });
  const isAdmin = session?.account?.role === "admin";
  const items = NAV.filter((item) => !item.admin || isAdmin);

  return (
    <div className="flex min-h-dvh flex-col bg-frame">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-background px-3 py-2 text-body font-medium focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:ring-2 focus:ring-ring"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-40 flex h-13 flex-none items-center gap-1 bg-frame px-3 md:gap-2 md:px-4">
        <MobileNav items={items} />
        <Link
          to="/"
          className="mr-2 inline-flex h-9 items-center gap-2 rounded-md pr-1 text-section font-semibold tracking-[-0.01em] outline-none focus-visible:ring-2 focus-visible:ring-ring md:mr-3"
        >
          <Mark />
          ExactDocs
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-0.5 md:flex">
          {items.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={bandLink}
              {...(current(item.to) && { "aria-current": "page" as const })}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex min-w-0 flex-1 items-center justify-end gap-1 md:gap-2">
          {search && (
            <>
              <div className="hidden w-full max-w-sm min-w-0 lg:block xl:max-w-md">{search}</div>
              {/* Below lg the box lives at the top of /search; the band keeps a door to it. */}
              <Link
                to="/search"
                // On /search itself the door keeps the query instead of wiping it.
                search={onSearch ? true : {}}
                aria-label="Search all libraries"
                className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "lg:hidden")}
              >
                <Search aria-hidden="true" className="size-[1.125rem]!" />
              </Link>
            </>
          )}
          <ThemeSwitch />
          <div className="hidden md:block">
            <UserMenu />
          </div>
        </div>
      </header>
      {/* The sheet: the page's own <main> lives inside. view-transition-name lets route changes
          cross-fade this region only (styles.css). */}
      <div className="flex min-w-0 flex-1 flex-col bg-background [view-transition-name:page] md:mx-2 md:mb-2 md:rounded-sheet md:border md:border-border">
        {children}
      </div>
    </div>
  );
}
