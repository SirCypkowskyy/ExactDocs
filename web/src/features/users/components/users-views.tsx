import { Link } from "@tanstack/react-router";
import { KeyRound, ListChecks, type LucideIcon, Users } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { messages } from "../messages";

/*
 * The users page's views as links that look like the kit's underline tabs: the accounts
 * (`/users`) and every account's API tokens (`/users/tokens`). Each view is its own URL with its
 * own table view, so these are links with `aria-current`, not a tablist.
 */

export type UsersViewName = "accounts" | "tokens" | "rules";

const VIEWS: readonly {
  name: UsersViewName;
  to: "/users" | "/users/tokens" | "/users/rules";
  icon: LucideIcon;
}[] = [
  { name: "accounts", to: "/users", icon: Users },
  { name: "tokens", to: "/users/tokens", icon: KeyRound },
  { name: "rules", to: "/users/rules", icon: ListChecks },
];

export function UsersViews({ current }: { current: UsersViewName }) {
  const t = useMessages(messages).views;
  return (
    <nav aria-label={t.label} className="mb-6">
      <ul className="flex gap-1 border-b border-border">
        {VIEWS.map(({ name, to, icon: Icon }) => {
          const here = name === current;
          return (
            <li key={name}>
              <Link
                to={to}
                aria-current={here ? "page" : undefined}
                className={cn(
                  "relative inline-flex h-11 items-center gap-2 rounded-t-md px-3 text-body font-medium text-muted-foreground outline-none transition-colors duration-(--dur-fast) focus-visible:ring-2 focus-visible:ring-ring fine:h-10 can-hover:hover:text-foreground [&_svg]:size-4",
                  here &&
                    "text-foreground after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 after:rounded-full after:bg-route",
                )}
              >
                <Icon aria-hidden="true" data-icon-motion="tilt" />
                {t[name]}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
