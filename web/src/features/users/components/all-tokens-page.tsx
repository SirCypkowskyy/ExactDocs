import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  CircleCheck,
  CircleSlash,
  CircleX,
  Clock,
  KeyRound,
  ListFilter,
  ScrollText,
  Users,
} from "lucide-react";
import { useMemo } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { useNow } from "@/shared/lib/use-now";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import { Badge } from "@/shared/ui/badge";
import { Chips, MonoCopy, Person, RelativeTime } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import type { ColumnDef } from "@/shared/ui/data-table/features";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import type { RowAction } from "@/shared/ui/data-table/row-actions";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import {
  type TableFilter,
  type TableParam,
  useDataTable,
} from "@/shared/ui/data-table/use-data-table";
import { Page, PageHeader } from "@/shared/ui/page";
import { allTokensSource } from "../api/users-query";
import { messages } from "../messages";
import {
  type AccountToken,
  ALL_TOKENS_TABLE,
  parseAllTokensView,
  TOKEN_EXPIRIES,
  TOKEN_USES,
} from "../model/all-tokens-view";
import { explainUserError } from "../model/user";
import { UsersViews } from "./users-views";

/*
 * Every account's API tokens, for an operator to tidy up (blocks-map §2.3, G7): who holds which
 * token, what it reaches, when it expires and when it was last used. Numbered pages sorted and
 * filtered by the server, the view in the URL. The API offers operators no revoke: disabling an
 * account or resetting its password revokes its tokens, which the page says.
 */

type Messages = (typeof messages)["en"];

const DAY = 86_400_000;

/** When it stops working: "in 12 days", a warning pill within a week, "Expired", or never. */
function ExpiresCell({ token }: { token: AccountToken }) {
  const t = useMessages(messages).tokens;
  const now = useNow();
  const at = token.expires_at;
  if (at === null) return <span className="text-muted-foreground">{t.noExpiry}</span>;
  const left = Date.parse(at) - now;
  if (left <= 0) {
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
  if (left < 7 * DAY) {
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
function NameCell({ token }: { token: AccountToken }) {
  const now = useNow();
  const expired = token.expires_at !== null && Date.parse(token.expires_at) <= now;
  return (
    <span
      className={cn("font-medium [overflow-wrap:anywhere]", expired && "text-muted-foreground")}
    >
      {token.name}
    </span>
  );
}

/** The libraries a token reaches: all its owner's, none, or the first two and the rest on demand. */
function LibrariesCell({ token }: { token: AccountToken }) {
  const t = useMessages(messages).tokens;
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

// Built once per language: a cell is rendered as a component, so a new function would remount it.
const columnsOf = (m: Messages): ColumnDef<AccountToken>[] => {
  const t = m.tokens;
  return [
    {
      accessorKey: "name",
      header: t.columns.name,
      enableHiding: false,
      meta: { priority: 1 },
      cell: ({ row }) => <NameCell token={row.original} />,
    },
    {
      accessorKey: "owner",
      header: t.columns.owner,
      enableHiding: false,
      meta: { priority: 2, skeleton: "avatar" },
      cell: ({ row }) => <Person name={row.original.owner} />,
    },
    {
      accessorKey: "prefix",
      header: t.columns.token,
      enableSorting: false,
      meta: { skeleton: "mono", className: "max-md:hidden" },
      cell: ({ row }) => (
        <MonoCopy value={row.original.prefix} display={`${row.original.prefix}…`} what={t.prefix} />
      ),
    },
    {
      id: "libraries",
      header: t.columns.libraries,
      enableSorting: false,
      meta: { label: t.columns.libraries, className: "max-lg:hidden" },
      cell: ({ row }) => <LibrariesCell token={row.original} />,
    },
    {
      accessorKey: "created_at",
      header: t.columns.created,
      sortDescFirst: true,
      meta: { className: "max-xl:hidden" },
      cell: ({ row }) => <RelativeTime iso={row.original.created_at} />,
    },
    {
      accessorKey: "expires_at",
      header: t.columns.expires,
      meta: { priority: 2, skeleton: "pill", label: t.columns.expires },
      cell: ({ row }) => <ExpiresCell token={row.original} />,
    },
    {
      accessorKey: "last_used_at",
      header: t.columns.used,
      sortDescFirst: true,
      meta: { priority: 3, label: t.columns.used },
      cell: ({ row }) => <RelativeTime iso={row.original.last_used_at} empty={t.neverUsed} />,
    },
  ];
};

const filtersOf = (m: Messages): TableFilter[] => [
  {
    id: "expiry",
    title: m.tokens.expiry,
    single: true,
    options: TOKEN_EXPIRIES.map((e) => ({
      value: e,
      label: m.tokens.expiries[e],
      icon: e === "expired" ? CircleX : CircleCheck,
    })),
  },
  {
    id: "use",
    title: m.tokens.use,
    single: true,
    options: TOKEN_USES.map((u) => ({
      value: u,
      label: m.tokens.uses[u],
      icon: u === "unused" ? CircleSlash : CircleCheck,
    })),
  },
];

/** The owner filter's chip names the account once a row tells its name; its ID until then. */
const paramsOf = (m: Messages, ownerName?: string): TableParam[] => [
  {
    id: "owner",
    title: m.tokens.owner,
    ...(ownerName ? { format: () => ownerName } : { mono: true }),
  },
];

/** Every account's API tokens (operators). */
export function AllTokensPage() {
  const view = parseAllTokensView(useSearch({ strict: false }) as Record<string, unknown>);
  const m = useMessages(messages);
  const t = m.tokens;
  const heading = usePageTitle(t.documentTitle);
  const navigate = useNavigate();
  const columns = useMemo(() => columnsOf(m), [m]);
  const filters = useMemo(() => filtersOf(m), [m]);
  const params = useMemo(() => paramsOf(m), [m]);
  const model = useDataTable({
    config: ALL_TOKENS_TABLE,
    search: view,
    columns,
    getRowId: (token) => token.id,
    filters,
    params,
    source: allTokensSource(view),
  });

  // Every row of an owner's tokens names the owner: the chip shows that name instead of the ID.
  const ownerName = model.rows.find((r) => r.original.owner_id === view.owner)?.original.owner;
  const toolbarModel = ownerName ? { ...model, params: paramsOf(m, ownerName) } : model;

  const actions = (token: AccountToken): RowAction<AccountToken>[] => [
    ...(view.owner === token.owner_id
      ? []
      : [
          {
            id: "owner-tokens",
            label: t.ownerTokens,
            icon: ListFilter,
            motion: "tilt" as const,
            onSelect: () => model.setParam("owner", token.owner_id),
          },
        ]),
    {
      id: "access-log",
      label: m.actions.accessLog,
      icon: ScrollText,
      motion: "tilt",
      onSelect: () => void navigate({ to: "/access-log", search: { actor: token.owner } }),
    },
  ];

  return (
    <Page>
      <PageHeader
        title={m.page.title}
        icon={<Users />}
        headingRef={heading}
        description={
          <>
            <p>{t.description}</p>
            {model.total !== undefined && (
              <p role="status" className="num mt-1">
                {t.count(model.total)}
              </p>
            )}
          </>
        }
      />
      <UsersViews current="tokens" />
      <DataTableToolbar
        model={toolbarModel}
        search={{ label: t.find, placeholder: t.findPlaceholder }}
      />
      <DataTable
        model={model}
        label={t.label}
        rowActions={actions}
        rowLabel={(token) => t.row(token.name, token.owner)}
        empty={{ icon: KeyRound, title: t.emptyTitle, body: t.emptyBody }}
        noMatch={{ title: t.noMatchTitle, body: m.list.noMatch }}
        errorMessage={model.error ? explainUserError(model.error) : t.loadFailed}
      />
      <DataTablePagination model={model} />
    </Page>
  );
}
