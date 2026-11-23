import { useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { ChevronDown, UserPlus, UserRound, Users } from "lucide-react";
import { createContext, type ReactNode, use, useMemo } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { Badge } from "@/shared/ui/badge";
import { Person } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import type { RowActions } from "@/shared/ui/data-table/row-actions";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import { type TableFilter, useDataTable } from "@/shared/ui/data-table/use-data-table";
import { select } from "@/shared/ui/recipes";
import { grantsSource } from "../api/grants";
import { messages, roleLabel, type SharingMessages } from "../messages";
import {
  type CallerRole,
  canManage,
  type Grant,
  type GrantedRole,
  givableRoles,
  grantKey,
} from "../model/grant";
import { GRANT_KINDS, GRANT_ROLES, GRANTS_TABLE, parseSharingView } from "../model/grants-view";

/*
 * Who holds a role on the library (blocks-map §2.3, "Grants"): DataTable v2 over the grants API,
 * which sorts, filters and pages; the view in the URL; a role select on the rows the caller may
 * change, and each row's actions in its kebab and its context menu.
 */

/** What a row's role select needs from the page: the columns stay the same between renders. */
interface RoleControl {
  caller: CallerRole;
  /** The grant whose change is on its way, as `kind:subject`. */
  busy: string | undefined;
  onRole: (grant: Grant, role: GrantedRole) => void;
}

const RoleContext = createContext<RoleControl>({
  caller: "admin",
  busy: undefined,
  onRole: () => {},
});

const KIND_ICONS = { user: UserRound, group: Users } as const;

/** A user as a person (initials and username); a group by its icon and exact name, in mono. */
function Subject({ grant }: { grant: Grant }) {
  if (grant.kind === "user") return <Person name={grant.subject} />;
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="inline-flex size-6 flex-none items-center justify-center rounded-full bg-secondary text-muted-foreground">
        <Users aria-hidden="true" className="size-3.5" />
      </span>
      <span className="font-mono text-mono [overflow-wrap:anywhere]">{grant.subject}</span>
    </span>
  );
}

function KindBadge({ grant }: { grant: Grant }) {
  const t = useMessages(messages);
  const Icon = KIND_ICONS[grant.kind];
  return (
    <Badge>
      <Icon aria-hidden="true" className="size-3" />
      {t.kinds[grant.kind]}
    </Badge>
  );
}

/** A select on rows the caller may change; the role as a pill otherwise (the creator's lit). */
function RoleCell({ grant }: { grant: Grant }) {
  const t = useMessages(messages);
  const { caller, busy, onRole } = use(RoleContext);
  if (!canManage(grant, caller)) {
    return (
      <Badge tone={grant.role === "creator" ? "route" : "neutral"}>
        {roleLabel(t, grant.role)}
      </Badge>
    );
  }
  return (
    <span className="relative -my-1.5 inline-block w-40">
      <select
        aria-label={t.table.roleOf(grant.subject)}
        value={grant.role}
        disabled={busy === grantKey(grant)}
        onChange={(e) => onRole(grant, e.target.value as GrantedRole)}
        className={select}
      >
        {givableRoles(caller).map((role) => (
          <option key={role} value={role}>
            {t.roles[role]}
          </option>
        ))}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
      />
    </span>
  );
}

// Built once per language, not per render: a cell is rendered as a component, so a new function
// would remount it. The headers stay strings: the sort buttons are named after them.
const columnsOf = (t: SharingMessages): ColumnDef<Grant>[] => [
  {
    accessorKey: "subject",
    header: t.table.who,
    enableHiding: false,
    meta: { priority: 1, skeleton: "avatar" },
    cell: ({ row }) => <Subject grant={row.original} />,
  },
  {
    accessorKey: "kind",
    header: t.table.kind,
    meta: { priority: 3, skeleton: "pill" },
    cell: ({ row }) => <KindBadge grant={row.original} />,
  },
  {
    accessorKey: "role",
    header: t.table.role,
    sortDescFirst: true,
    enableHiding: false,
    meta: { priority: 2, skeleton: "pill" },
    cell: ({ row }) => <RoleCell grant={row.original} />,
  },
];

const filtersOf = (t: SharingMessages): TableFilter[] => [
  {
    id: "kind",
    title: t.table.kind,
    options: GRANT_KINDS.map((k) => ({ value: k, label: t.kindsPlural[k], icon: KIND_ICONS[k] })),
  },
  {
    id: "role",
    title: t.table.role,
    options: GRANT_ROLES.map((r) => ({ value: r, label: t.roles[r] })),
  },
];

interface Props extends RoleControl {
  owner: string;
  repo: string;
  rowActions: RowActions<Grant>;
  /** The way to share it, for a table that turns out empty. */
  shareAction: ReactNode;
}

/** Who holds a role on the library: sorted, filtered and paged by the server, the view in the URL. */
export function GrantsTable({ owner, repo, rowActions, shareAction, ...control }: Props) {
  const t = useMessages(messages);
  const view = parseSharingView(useSearch({ strict: false }) as Record<string, unknown>);
  const columns = useMemo(() => columnsOf(t), [t]);
  const filters = useMemo(() => filtersOf(t), [t]);
  const model = useDataTable({
    config: GRANTS_TABLE,
    search: view,
    columns,
    getRowId: grantKey,
    filters,
    source: grantsSource(owner, repo, view),
  });
  return (
    <RoleContext value={control}>
      <DataTableToolbar
        model={model}
        search={{ label: t.table.find, placeholder: t.table.findPlaceholder }}
      />
      <DataTable
        model={model}
        label={t.table.label}
        rowActions={rowActions}
        rowLabel={(grant) => grant.subject}
        empty={{
          icon: UserPlus,
          title: t.page.emptyTitle,
          body: t.page.empty,
          action: shareAction,
        }}
        noMatch={{ title: t.table.nobody }}
        errorMessage={t.table.loadFailed}
      />
      <DataTablePagination model={model} />
    </RoleContext>
  );
}
