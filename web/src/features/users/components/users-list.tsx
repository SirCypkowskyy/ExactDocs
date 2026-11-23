import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { type ReactNode, useEffect, useEffectEvent, useId, useState } from "react";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { EmptyState } from "@/shared/ui/page";
import { SelectField } from "@/shared/ui/select-field";
import { Skeleton } from "@/shared/ui/skeleton";
import type { UsersView } from "../model/list-view";
import type { User } from "../model/user";

// Account | Role | Status | Created | Actions. Below `md` the pills sit under the name.
export const columns =
  "md:grid md:grid-cols-[minmax(0,1fr)_5rem_6rem_7.5rem_auto] md:items-center md:gap-x-4";

/** Sorting is done by the API, so the table only holds the state and draws the headers. */
const columnDefs: ColumnDef<User>[] = [
  { accessorKey: "username", header: "Account" },
  { accessorKey: "role", header: "Role" },
  { id: "status", header: "Status", enableSorting: false },
  { accessorKey: "created_at", header: "Created", sortDescFirst: true },
  { id: "actions", header: "", enableSorting: false },
];
const sortingOf = (sort: string | undefined): SortingState =>
  sort ? [{ id: sort.replace(/^-/, ""), desc: sort.startsWith("-") }] : [];

interface UsersListProps {
  users: readonly User[];
  view: UsersView;
  onView: (view: UsersView) => void;
  total: number;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  row: (user: User) => ReactNode;
}

function Toolbar({
  view,
  onView,
  text,
  setText,
}: Pick<UsersListProps, "view" | "onView"> & { text: string; setText: (v: string) => void }) {
  const id = useId();
  const commit = useEffectEvent((value: string) => {
    if ((view.q ?? "") !== value.trim()) onView({ ...view, q: value.trim() || undefined });
  });
  // Typing waits a moment before it asks the server.
  useEffect(() => {
    const t = setTimeout(() => commit(text), 300);
    return () => clearTimeout(t);
  }, [text]);
  return (
    <search className="mb-4 flex flex-wrap items-end gap-3">
      <div className="flex min-w-0 flex-1 basis-60 flex-col gap-2">
        <label htmlFor={`${id}-q`} className="text-body font-medium">
          Find an account
        </label>
        <Input
          id={`${id}-q`}
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Username"
        />
      </div>
      <div className="w-36">
        <SelectField
          id={`${id}-role`}
          label="Role"
          value={view.role ?? ""}
          onChange={(e) =>
            onView({ ...view, role: (e.target.value || undefined) as UsersView["role"] })
          }
        >
          <option value="">Any</option>
          <option value="admin">Admin</option>
          <option value="user">User</option>
        </SelectField>
      </div>
      <div className="w-36">
        <SelectField
          id={`${id}-status`}
          label="Status"
          value={view.status ?? ""}
          onChange={(e) =>
            onView({ ...view, status: (e.target.value || undefined) as UsersView["status"] })
          }
        >
          <option value="">Any</option>
          <option value="active">Active</option>
          <option value="disabled">Disabled</option>
        </SelectField>
      </div>
      <div className="w-48 md:hidden">
        <SelectField
          id={`${id}-sort`}
          label="Sort by"
          value={view.sort ?? ""}
          onChange={(e) => onView({ ...view, sort: e.target.value || undefined })}
        >
          <option value="">Oldest first</option>
          <option value="-created_at">Newest first</option>
          <option value="username">Name, A to Z</option>
          <option value="-username">Name, Z to A</option>
          <option value="role">Admins first</option>
        </SelectField>
      </div>
    </search>
  );
}

/** The users table: server-side sort and filters, a page at a time, view state from the URL. */
export function UsersList({
  users,
  view,
  onView,
  total,
  hasMore,
  loadingMore,
  onLoadMore,
  row,
}: UsersListProps) {
  const [text, setText] = useState(view.q ?? "");
  const table = useReactTable({
    data: users as User[],
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (user) => user.id,
    manualSorting: true,
    manualFiltering: true,
    state: { sorting: sortingOf(view.sort) },
    onSortingChange: (updater) => {
      const [next] = typeof updater === "function" ? updater(sortingOf(view.sort)) : updater;
      onView({ ...view, sort: next ? `${next.desc ? "-" : ""}${next.id}` : undefined });
    },
  });
  return (
    <div>
      <Toolbar view={view} onView={onView} text={text} setText={setText} />
      {users.length === 0 ? (
        <EmptyState title="No accounts match" className="max-w-2xl">
          <p>Nothing matches these filters.</p>
          <Button
            variant="ghost"
            className="mt-3"
            onClick={() => {
              setText("");
              onView({ sort: view.sort });
            }}
          >
            Clear filters
          </Button>
        </EmptyState>
      ) : (
        <>
          <div
            className={cn(
              "hidden border-b border-border pb-2 text-small text-muted-foreground",
              columns,
            )}
          >
            {table.getHeaderGroups()[0]?.headers.map((header) => {
              const dir = header.column.getIsSorted();
              const label = flexRender(header.column.columnDef.header, header.getContext());
              if (!header.column.getCanSort()) {
                return (
                  <span key={header.id} className={header.id === "actions" ? "w-44" : undefined}>
                    {label}
                  </span>
                );
              }
              return (
                <span key={header.id}>
                  <button
                    type="button"
                    aria-label={`Sort by ${String(header.column.columnDef.header)}${dir ? `, sorted ${dir === "asc" ? "ascending" : "descending"}` : ""}`}
                    onClick={header.column.getToggleSortingHandler()}
                    className="inline-flex cursor-pointer items-center gap-1 rounded outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {label}
                    {dir === "asc" ? (
                      <ArrowUp aria-hidden="true" className="size-3.5" />
                    ) : dir === "desc" ? (
                      <ArrowDown aria-hidden="true" className="size-3.5" />
                    ) : (
                      <ArrowUpDown aria-hidden="true" className="size-3.5 opacity-50" />
                    )}
                  </button>
                </span>
              );
            })}
          </div>
          <ul
            aria-label="User accounts"
            className="divide-y divide-rule border-b border-border md:border-t-0 max-md:border-t"
          >
            {table.getRowModel().rows.map(({ original }) => row(original))}
            {loadingMore && (
              <li aria-hidden="true" className="py-4">
                <Skeleton className="h-12 w-full" />
              </li>
            )}
          </ul>
          <div className="flex items-center gap-3 pt-4 text-small text-muted-foreground">
            <p className="num">
              Showing {users.length} of {total}
            </p>
            {hasMore && (
              <Button variant="outline" onClick={onLoadMore} disabled={loadingMore}>
                Load more
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
