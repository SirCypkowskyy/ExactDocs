import { useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useRouter } from "@tanstack/react-router";
import {
  Activity,
  Cpu,
  FlaskConical,
  KeyRound,
  LibraryBig,
  LogOut,
  type LucideIcon,
  Menu,
  ScrollText,
  Search,
  Users,
} from "lucide-react";
import { type ReactNode, useState } from "react";
import { toast } from "sonner";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/shared/ui/accordion";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/shared/ui/dropdown-menu";
import { bandIconButton, InterfaceCluster } from "@/shared/ui/interface-controls";
import {
  NavigationMenu,
  NavigationMenuContent,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  NavigationMenuPlainLink,
  NavigationMenuTrigger,
  navigationMenuTriggerStyle,
} from "@/shared/ui/navigation-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/shared/ui/sheet";
import { Tooltip } from "@/shared/ui/tooltip";
import { Wordmark } from "@/shared/ui/wordmark";
import { signOut } from "../api/session-query";
import { usePreferencesSync } from "../hooks/use-preferences-sync";
import { useSession } from "../hooks/use-session";
import { messages, roleName } from "../messages";

/*
 * The app shell, after the free shadcnblocks navbars 1, 5 and 35 (a navigation menu whose panels
 * list icon links with one line each, a phone sheet with an accordion) and "Application Shell 3"
 * (the frame and the sheet). The band holds the sign, the two places people work in every day as
 * direct links, the rest in two panels, and the interface console; the page lives on the sheet.
 */

type To = "/" | "/jobs" | "/search" | "/playground" | "/ai" | "/users" | "/access-log";
type Nav = (typeof messages)["en"]["nav"];
/** `motion`: the icon's reaction when its row is hovered or focused (app/icon-motion.css). */
type Motion = "tilt" | "pop" | "down";
type Entry = { to: To; label: string; description: string; icon: LucideIcon; motion: Motion };
type Group = { id: string; label: string; admin?: boolean; items: Entry[] };

/** Where people work every day: one click away. */
const primary = (t: Nav): Entry[] => [
  { to: "/", label: t.libraries, description: t.librariesHint, icon: LibraryBig, motion: "tilt" },
  { to: "/search", label: t.search, description: t.searchHint, icon: Search, motion: "tilt" },
];

/** Everything else, in panels. Admin pages are for operators; the API refuses anyone else. */
const groups = (t: Nav): Group[] => [
  {
    id: "tools",
    label: t.tools,
    items: [
      {
        to: "/playground",
        label: t.playground,
        description: t.playgroundHint,
        icon: FlaskConical,
        motion: "tilt",
      },
      { to: "/jobs", label: t.jobs, description: t.jobsHint, icon: Activity, motion: "pop" },
    ],
  },
  {
    id: "admin",
    label: t.admin,
    admin: true,
    items: [
      { to: "/ai", label: t.ai, description: t.aiHint, icon: Cpu, motion: "pop" },
      { to: "/users", label: t.users, description: t.usersHint, icon: Users, motion: "pop" },
      {
        to: "/access-log",
        label: t.accessLog,
        description: t.accessLogHint,
        icon: ScrollText,
        motion: "down",
      },
    ],
  },
];

function useCurrent() {
  const pathname = useLocation({ select: (l) => l.pathname });
  // Libraries owns `/` and everything under `/libraries`, so it stays lit on the add screen.
  return (to: To) =>
    to === "/" ? pathname === "/" || pathname.startsWith("/libraries") : pathname === to;
}

function useSignOut() {
  const t = useMessages(messages);
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
      toast.error(t.signOut.failed);
    } finally {
      setPending(false);
    }
  }
  return { pending, run };
}

function initials(name: string): string {
  return name.slice(0, 1).toUpperCase() || "?";
}

/** One row of a panel or of the phone's accordion: icon, name, one line on what is there. */
function EntryRow({ entry }: { entry: Entry }) {
  const Icon = entry.icon;
  return (
    <>
      <Icon
        aria-hidden="true"
        data-icon-motion={entry.motion}
        className="mt-0.5 size-[1.125rem] flex-none text-foreground"
      />
      <span className="grid gap-0.5">
        <span className="font-medium text-foreground">{entry.label}</span>
        <span className="text-small text-muted-foreground">{entry.description}</span>
      </span>
    </>
  );
}

function DesktopNav({ entries, groups }: { entries: Entry[]; groups: Group[] }) {
  const current = useCurrent();
  const t = useMessages(messages);
  return (
    <NavigationMenu aria-label={t.nav.main} className="hidden md:flex">
      <NavigationMenuList>
        {entries.map((entry) => (
          <NavigationMenuItem key={entry.to}>
            <NavigationMenuPlainLink asChild active={current(entry.to)}>
              <Link to={entry.to} className={navigationMenuTriggerStyle()}>
                {entry.label}
              </Link>
            </NavigationMenuPlainLink>
          </NavigationMenuItem>
        ))}
        {groups.map((group) => {
          const lit = group.items.some((entry) => current(entry.to));
          return (
            <NavigationMenuItem key={group.id}>
              <NavigationMenuTrigger data-active={lit || undefined}>
                {group.label}
              </NavigationMenuTrigger>
              <NavigationMenuContent>
                <ul className="grid w-[23rem] gap-0.5">
                  {group.items.map((entry) => (
                    <li key={entry.to}>
                      <NavigationMenuLink asChild active={current(entry.to)}>
                        <Link to={entry.to}>
                          <EntryRow entry={entry} />
                        </Link>
                      </NavigationMenuLink>
                    </li>
                  ))}
                </ul>
              </NavigationMenuContent>
            </NavigationMenuItem>
          );
        })}
      </NavigationMenuList>
    </NavigationMenu>
  );
}

function UserMenu() {
  const session = useSession();
  const account = session?.account;
  const t = useMessages(messages);
  const { pending, run } = useSignOut();
  if (!account) return null;
  // Cloudflare Access signs this browser in on every request: ending only the ExactDocs session
  // would sign it straight back in. Access's own logout ends both.
  const accessSignOut = session?.source === "cloudflare_access" ? session.sign_out_url : null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t.account.menuLabel(account.username)}
        className="inline-flex h-11 min-w-0 cursor-pointer items-center gap-2 rounded-md px-1.5 text-body outline-none transition-[background-color,transform] duration-(--dur-fast) ease-(--ease-out) focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] data-[state=open]:bg-band-hover fine:h-9 can-hover:hover:bg-band-hover lg:pr-2.5"
      >
        <span
          aria-hidden="true"
          className="inline-flex size-7 flex-none items-center justify-center rounded-full bg-primary text-small font-semibold text-primary-foreground"
        >
          {initials(account.username)}
        </span>
        <span className="hidden max-w-[10rem] truncate font-medium lg:inline">
          {account.username}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <span className="block truncate text-body font-medium">{account.username}</span>
          <span className="block text-small text-muted-foreground capitalize">
            {roleName(t.roles, account.role)}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/account">
            <KeyRound aria-hidden="true" data-icon-motion="tilt" />
            {t.account.accountAndTokens}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {accessSignOut ? (
          <DropdownMenuItem asChild>
            <a href={accessSignOut} title={t.signOut.accessHint}>
              <LogOut aria-hidden="true" data-icon-motion="forward" />
              {t.signOut.action}
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
            <LogOut aria-hidden="true" data-icon-motion="forward" />
            {pending ? t.signOut.pendingMenu : t.signOut.action}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** The phone's navigation: a sheet from the left, the daily places first, the panels as an accordion. */
function MobileNav({ entries, groups }: { entries: Entry[]; groups: Group[] }) {
  const [open, setOpen] = useState(false);
  const t = useMessages(messages);
  const current = useCurrent();
  const session = useSession();
  const { pending, run } = useSignOut();
  const accessSignOut = session?.source === "cloudflare_access" ? session.sign_out_url : null;
  const row =
    "flex min-h-11 items-start gap-3 rounded-md px-3 py-2.5 text-body outline-none transition-colors duration-(--dur-fast) focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:bg-route-soft can-hover:hover:bg-accent";
  const close = () => setOpen(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <Tooltip label={t.nav.menu}>
        <SheetTrigger aria-label={t.nav.menu} className={cn(bandIconButton, "-ml-1.5 md:hidden")}>
          <Menu aria-hidden="true" className="size-5!" />
        </SheetTrigger>
      </Tooltip>
      <SheetContent side="left" className="w-[min(22rem,88vw)] gap-0 p-0">
        <div className="flex h-14 items-center px-4">
          <SheetTitle className="sr-only">ExactDocs</SheetTitle>
          <Wordmark className="h-7" />
          <SheetDescription className="sr-only">{t.nav.sheetDescription}</SheetDescription>
        </div>
        <nav aria-label={t.nav.main} className="flex flex-col gap-0.5 overflow-y-auto px-2 pb-2">
          {entries.map((entry) => (
            <Link
              key={entry.to}
              to={entry.to}
              onClick={close}
              className={row}
              {...(current(entry.to) && { "aria-current": "page" as const })}
            >
              <EntryRow entry={entry} />
            </Link>
          ))}
          <Accordion
            type="multiple"
            defaultValue={groups.filter((g) => g.items.some((e) => current(e.to))).map((g) => g.id)}
            className="mt-1"
          >
            {groups.map((group) => (
              <AccordionItem key={group.id} value={group.id}>
                <AccordionTrigger>{group.label}</AccordionTrigger>
                <AccordionContent className="grid gap-0.5">
                  {group.items.map((entry) => (
                    <Link
                      key={entry.to}
                      to={entry.to}
                      onClick={close}
                      className={row}
                      {...(current(entry.to) && { "aria-current": "page" as const })}
                    >
                      <EntryRow entry={entry} />
                    </Link>
                  ))}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </nav>
        <div className="mt-auto grid gap-0.5 border-t border-border px-2 py-2">
          <Link
            to="/account"
            onClick={close}
            className={row}
            activeProps={{ "aria-current": "page" }}
          >
            <KeyRound aria-hidden="true" data-icon-motion="tilt" className="mt-0.5 size-4" />
            {t.account.accountAndTokens}
          </Link>
          {accessSignOut ? (
            <a href={accessSignOut} className={row}>
              <LogOut aria-hidden="true" data-icon-motion="forward" className="mt-0.5 size-4" />
              {t.signOut.action}
            </a>
          ) : (
            <button
              type="button"
              className={cn(row, "w-full cursor-pointer")}
              aria-busy={pending}
              onClick={() => void run()}
            >
              <LogOut aria-hidden="true" data-icon-motion="forward" className="mt-0.5 size-4" />
              {pending ? t.signOut.pendingMenu : t.signOut.action}
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
  usePreferencesSync(Boolean(session?.account));
  const t = useMessages(messages);
  const onSearch = useLocation({ select: (l) => l.pathname === "/search" });
  const isAdmin = session?.account?.role === "admin";
  const entries = primary(t.nav);
  const visible = groups(t.nav).filter((group) => !group.admin || isAdmin);

  return (
    <div className="flex min-h-dvh flex-col bg-frame">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-background px-3 py-2 text-body font-medium focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:ring-2 focus:ring-ring"
      >
        {t.nav.skipToContent}
      </a>
      <header className="sticky top-0 z-40 flex h-14 flex-none items-center gap-1 bg-frame px-3 md:gap-3 md:px-4">
        <MobileNav entries={entries} groups={visible} />
        <Link
          to="/"
          aria-label={t.nav.home}
          className="inline-flex h-11 flex-none items-center rounded-md px-1 outline-none transition-transform duration-(--dur-fast) ease-(--ease-out) focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] fine:h-9"
        >
          <Wordmark className="h-7" />
        </Link>
        <span aria-hidden="true" className="mx-1 hidden h-5 w-px bg-border md:block" />
        <DesktopNav entries={entries} groups={visible} />
        <div className="ml-auto flex min-w-0 flex-1 items-center justify-end gap-1 md:gap-2">
          {search && (
            <>
              <div className="hidden w-full max-w-xs min-w-0 xl:block">{search}</div>
              {/* Below xl the box lives at the top of /search; the band keeps a door to it. */}
              <Tooltip label={t.nav.searchAll} shortcut="/">
                <Link
                  to="/search"
                  // On /search itself the door keeps the query instead of wiping it.
                  search={onSearch ? true : {}}
                  aria-label={t.nav.searchAll}
                  className={cn(bandIconButton, "xl:hidden")}
                >
                  <Search aria-hidden="true" data-icon-motion="tilt" />
                </Link>
              </Tooltip>
            </>
          )}
          <InterfaceCluster />
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
