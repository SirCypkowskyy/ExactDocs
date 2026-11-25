import { CircleX, Clock, Infinity as Endless } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { useNow } from "@/shared/lib/use-now";
import { cn } from "@/shared/lib/utils";
import { Badge } from "@/shared/ui/badge";
import { Chips, MonoCopy, RelativeTime } from "@/shared/ui/data-table/cells";
import type { ColumnDef, FilterFn, SortFn } from "@/shared/ui/data-table/features";
import type { TableFilter } from "@/shared/ui/data-table/use-data-table";
import { messages } from "../messages";
import {
  expiryOf,
  lastUseOf,
  scopeOf,
  sortTime,
  TOKEN_EXPIRIES,
  TOKEN_SCOPES,
  TOKEN_USES,
} from "../model/list-view";
import type { Token } from "../model/token";

/*
 * The token table's columns and filters (blocks-map §2.3, API tokens). The filterable columns hold
 * a token's category (its scope, how soon it expires, how recently it was used), so the browser
 * filters and counts them; the time columns still sort by the time itself.
 */

type TokensMessages = (typeof messages)["en"];

/** A row matches when its category is one of the picked values. */
const inList: FilterFn<Token> = (row, id, values: readonly string[]) =>
  values.includes(row.getValue<string>(id));

/** Sorts by a time of the token (never first ascending), not by the column's category. */
const byTime =
  (field: "expires_at" | "last_used_at"): SortFn<Token> =>
  (a, b) => {
    const x = sortTime(a.original[field]);
    const y = sortTime(b.original[field]);
    return x < y ? -1 : x > y ? 1 : 0;
  };

/** The libraries a token reaches: all, none, or the first two as chips and the rest on demand. */
function LibrariesCell({ token }: { token: Token }) {
  const t = useMessages(messages).list;
  const ids = token.library_ids;
  if (ids == null) return <span className="text-muted-foreground">{t.allLibraries}</span>;
  return (
    <Chips
      items={ids}
      more={(n) => t.moreLibraries(n, token.name)}
      title={t.librariesOf(token.name)}
      empty={t.noLibraries}
    />
  );
}

/** When it stops working: "in 12 days", a warning pill within a week, "Expired", or no expiry. */
function ExpiresCell({ token }: { token: Token }) {
  const t = useMessages(messages).list;
  const now = useNow();
  const at = token.expires_at;
  if (at === null) return <span className="text-muted-foreground">{t.noExpiry}</span>;
  const expiry = expiryOf(token, now);
  if (expiry === "expired") {
    return (
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Badge tone="destructive">
          <CircleX aria-hidden="true" className="size-3" />
          {t.expired}
        </Badge>
        <span className="text-muted-foreground">
          <RelativeTime iso={at} />
        </span>
      </span>
    );
  }
  if (expiry === "soon") {
    return (
      <Badge tone="warning">
        <Clock aria-hidden="true" className="size-3" />
        <RelativeTime iso={at} future />
      </Badge>
    );
  }
  return <RelativeTime iso={at} future />;
}

/** The name, muted once the token has expired. */
function NameCell({ token }: { token: Token }) {
  const expired = expiryOf(token, useNow()) === "expired";
  return (
    <span
      className={cn("font-medium [overflow-wrap:anywhere]", expired && "text-muted-foreground")}
    >
      {token.name}
    </span>
  );
}

// Built once per language: a cell is rendered as a component, so a new function would remount it.
export const columnsOf = (m: TokensMessages): ColumnDef<Token>[] => [
  {
    accessorKey: "name",
    header: m.list.columns.name,
    enableHiding: false,
    meta: { priority: 1 },
    cell: ({ row }) => <NameCell token={row.original} />,
  },
  {
    accessorKey: "prefix",
    header: m.list.columns.token,
    enableSorting: false,
    enableGlobalFilter: false,
    meta: { priority: 2, skeleton: "mono" },
    cell: ({ row }) => (
      <MonoCopy
        value={row.original.prefix}
        display={`${row.original.prefix}…`}
        what={m.list.prefix}
      />
    ),
  },
  {
    id: "libraries",
    accessorFn: scopeOf,
    header: m.list.columns.libraries,
    enableSorting: false,
    enableGlobalFilter: false,
    filterFn: inList,
    meta: { className: "max-lg:hidden" },
    cell: ({ row }) => <LibrariesCell token={row.original} />,
  },
  {
    id: "created",
    accessorFn: (token) => Date.parse(token.created_at),
    header: m.list.columns.created,
    sortDescFirst: true,
    enableGlobalFilter: false,
    meta: { className: "max-md:hidden" },
    cell: ({ row }) => <RelativeTime iso={row.original.created_at} />,
  },
  {
    id: "expires",
    accessorFn: (token) => expiryOf(token, Date.now()),
    header: m.list.columns.expires,
    enableGlobalFilter: false,
    filterFn: inList,
    sortFn: byTime("expires_at"),
    meta: { priority: 2, skeleton: "pill" },
    cell: ({ row }) => <ExpiresCell token={row.original} />,
  },
  {
    id: "used",
    accessorFn: (token) => lastUseOf(token, Date.now()),
    header: m.list.columns.used,
    sortDescFirst: true,
    enableGlobalFilter: false,
    filterFn: inList,
    sortFn: byTime("last_used_at"),
    meta: { priority: 3 },
    cell: ({ row }) => <RelativeTime iso={row.original.last_used_at} empty={m.list.neverUsed} />,
  },
];

/** The same marks as the expiry cell's pills. */
const EXPIRY_ICONS = { expired: CircleX, soon: Clock, never: Endless } as const;

export const filtersOf = (m: TokensMessages): TableFilter[] => [
  {
    id: "libraries",
    title: m.list.columns.libraries,
    options: TOKEN_SCOPES.map((s) => ({ value: s, label: m.list.scopes[s] })),
  },
  {
    id: "expires",
    title: m.list.columns.expires,
    options: TOKEN_EXPIRIES.map((e) => ({
      value: e,
      label: m.list.expiries[e],
      icon: EXPIRY_ICONS[e],
    })),
  },
  {
    id: "used",
    title: m.list.columns.used,
    options: TOKEN_USES.map((u) => ({ value: u, label: m.list.uses[u] })),
  },
];
