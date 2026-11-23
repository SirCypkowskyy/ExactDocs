import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { type ReactNode, useEffect, useEffectEvent, useId, useMemo, useState } from "react";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { EmptyState } from "@/shared/ui/page";
import { SelectField } from "@/shared/ui/select-field";
import { Skeleton } from "@/shared/ui/skeleton";
import { messages } from "../messages";
import { columnsFor } from "../model/columns";
import type { UsersView } from "../model/list-view";
import type { User } from "../model/user";

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
  const { list: t, roles } = useMessages(messages);
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
          {t.find}
        </label>
        <Input
          id={`${id}-q`}
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t.usernamePlaceholder}
        />
      </div>
      <div className="w-36">
        <SelectField
          id={`${id}-role`}
          label={t.role}
          value={view.role ?? ""}
          onChange={(e) =>
            onView({ ...view, role: (e.target.value || undefined) as UsersView["role"] })
          }
        >
          <option value="">{t.anyRole}</option>
          <option value="admin">{roles.admin}</option>
          <option value="user">{roles.user}</option>
        </SelectField>
      </div>
      <div className="w-36">
        <SelectField
          id={`${id}-status`}
          label={t.status}
          value={view.status ?? ""}
          onChange={(e) =>
            onView({ ...view, status: (e.target.value || undefined) as UsersView["status"] })
          }
        >
          <option value="">{t.anyStatus}</option>
          <option value="active">{t.active}</option>
          <option value="disabled">{t.disabled}</option>
        </SelectField>
      </div>
      <div className="w-48 md:hidden">
        <SelectField
          id={`${id}-sort`}
          label={t.sortLabel}
          value={view.sort ?? ""}
          onChange={(e) => onView({ ...view, sort: e.target.value || undefined })}
        >
          <option value="">{t.sort.oldest}</option>
          <option value="-created_at">{t.sort.newest}</option>
          <option value="username">{t.sort.nameAsc}</option>
          <option value="-username">{t.sort.nameDesc}</option>
          <option value="role">{t.sort.adminsFirst}</option>
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
  const language = useLanguage();
  const t = useMessages(messages).list;
  const columns = columnsFor(language);
  // Sorting is done by the API, so the table only holds the state and draws the headers.
  const columnDefs = useMemo<ColumnDef<User>[]>(
    () => [
      { accessorKey: "username", header: t.columns.account },
      { accessorKey: "role", header: t.columns.role },
      { id: "status", header: t.columns.status, enableSorting: false },
      { accessorKey: "created_at", header: t.columns.created, sortDescFirst: true },
      { id: "actions", header: "", enableSorting: false },
    ],
    [t],
  );
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
        <EmptyState title={t.noMatchTitle} className="max-w-2xl">
          <p>{t.noMatch}</p>
          <Button
            variant="ghost"
            className="mt-3"
            onClick={() => {
              setText("");
              onView({ sort: view.sort });
            }}
          >
            {t.clearFilters}
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
                    aria-label={t.sortBy(String(header.column.columnDef.header), dir)}
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
            aria-label={t.label}
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
            <p className="num">{t.showing(users.length, total)}</p>
            {hasMore && (
              <Button variant="outline" onClick={onLoadMore} disabled={loadingMore}>
                {t.loadMore}
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
