import type { ColumnDef } from "@tanstack/react-table";
import { ChevronDown, Users } from "lucide-react";
import { createContext, use, useId } from "react";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { DataTable, ListFooter, SearchFilter, useServerTable } from "@/shared/ui/data-table";
import { pill, pillTone, select } from "@/shared/ui/recipes";
import { SelectField } from "@/shared/ui/select-field";
import {
  type CallerRole,
  canManage,
  type Grant,
  type GrantedRole,
  givableRoles,
  grantKey,
  KIND_LABELS,
  ROLE_LABELS,
} from "../model/grant";
import { GRANT_KINDS, GRANT_ROLES, parseSharingView, type SharingView } from "../model/grants-view";

/** What a row may do, from the page: the columns stay the same between renders. */
interface RowActions {
  caller: CallerRole;
  /** The grant whose change is on its way, as `kind:subject`. */
  busy: string | undefined;
  onRole: (grant: Grant, role: GrantedRole) => void;
  onRemove: (grant: Grant) => void;
}

const RowContext = createContext<RowActions>({
  caller: "admin",
  busy: undefined,
  onRole: () => {},
  onRemove: () => {},
});

function Subject({ grant }: { grant: Grant }) {
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span
        className={cn(
          "font-medium [overflow-wrap:anywhere]",
          grant.kind === "group" && "font-mono",
        )}
      >
        {grant.subject}
      </span>
      {grant.kind === "group" && (
        <span className={cn(pill, pillTone.neutral, "md:hidden")}>Group</span>
      )}
    </span>
  );
}

function RoleCell({ grant }: { grant: Grant }) {
  const { caller, busy, onRole } = use(RowContext);
  if (!canManage(grant, caller)) {
    return (
      <span className={cn(pill, grant.role === "creator" ? pillTone.route : pillTone.neutral)}>
        {ROLE_LABELS[grant.role] ?? grant.role}
      </span>
    );
  }
  const roles = givableRoles(caller);
  return (
    <span className="relative -my-1.5 inline-block w-40">
      <select
        aria-label={`Role of ${grant.subject}`}
        value={grant.role}
        disabled={busy === grantKey(grant)}
        onChange={(e) => onRole(grant, e.target.value as GrantedRole)}
        className={select}
      >
        {roles.map((role) => (
          <option key={role} value={role}>
            {ROLE_LABELS[role]}
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

function RemoveButton({ grant }: { grant: Grant }) {
  const { caller, onRemove } = use(RowContext);
  if (!canManage(grant, caller)) return null;
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-label={`Remove ${grant.subject}`}
      onClick={() => onRemove(grant)}
      className="-my-1.5 text-muted-foreground hover:bg-destructive-soft hover:text-destructive focus-visible:text-destructive"
    >
      Remove
    </Button>
  );
}

// Module level on purpose: a cell is rendered as a component, so a new function would remount it.
const columns: ColumnDef<Grant>[] = [
  {
    accessorKey: "subject",
    header: "Who",
    cell: ({ row }) => <Subject grant={row.original} />,
  },
  {
    accessorKey: "kind",
    header: "Kind",
    meta: { className: "max-md:hidden" },
    cell: ({ row }) => KIND_LABELS[row.original.kind],
  },
  {
    accessorKey: "role",
    header: "Role",
    sortDescFirst: true,
    cell: ({ row }) => <RoleCell grant={row.original} />,
  },
  {
    id: "actions",
    header: "Actions",
    enableSorting: false,
    meta: { className: "w-28 text-right" },
    cell: ({ row }) => <RemoveButton grant={row.original} />,
  },
];

interface Props extends RowActions {
  grants: readonly Grant[];
  view: SharingView;
  onView: (view: SharingView) => void;
  total: number;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}

/** Who holds a role on the library: sorted and filtered by the server, the view in the URL. */
export function GrantsTable({
  grants,
  view,
  onView,
  total,
  hasMore,
  loadingMore,
  onLoadMore,
  ...actions
}: Props) {
  const id = useId();
  const table = useServerTable({
    data: grants,
    columns,
    getRowId: grantKey,
    sort: view.sort,
    onSort: (sort) => onView({ ...view, sort }),
  });
  return (
    <RowContext value={actions}>
      <search className="mb-3 flex flex-wrap items-end gap-3">
        <SearchFilter
          id={`${id}-q`}
          label="Find a person or group"
          placeholder="Username or group"
          value={view.q}
          onCommit={(q) => onView({ ...view, q })}
        />
        <div className="w-32">
          <SelectField
            id={`${id}-kind`}
            label="Kind"
            value={view.kind ?? ""}
            onChange={(e) =>
              onView({ ...view, kind: parseSharingView({ kind: e.target.value }).kind })
            }
          >
            <option value="">Any</option>
            {GRANT_KINDS.map((k) => (
              <option key={k} value={k}>
                {KIND_LABELS[k]}s
              </option>
            ))}
          </SelectField>
        </div>
        <div className="w-36">
          <SelectField
            id={`${id}-role`}
            label="Role"
            value={view.role ?? ""}
            onChange={(e) =>
              onView({ ...view, role: parseSharingView({ role: e.target.value }).role })
            }
          >
            <option value="">Any</option>
            {GRANT_ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </SelectField>
        </div>
      </search>
      {grants.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed border-input px-5 py-6">
          <Users aria-hidden="true" className="size-5 text-muted-foreground" />
          <p className="text-body">
            <span className="font-medium">Nobody matches.</span>{" "}
            <button
              type="button"
              onClick={() => onView({ sort: view.sort })}
              className="cursor-pointer font-medium underline underline-offset-2"
            >
              Clear filters
            </button>
          </p>
        </div>
      ) : (
        <>
          <DataTable table={table} label="Who has access" loadingMore={loadingMore} />
          <ListFooter
            shown={grants.length}
            total={total}
            hasMore={hasMore}
            loadingMore={loadingMore}
            onLoadMore={onLoadMore}
          />
        </>
      )}
    </RowContext>
  );
}
