import {
  type ColumnDef,
  getCoreRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { useEffect, useEffectEvent, useId, useState } from "react";
import { UI_LOCALE } from "@/shared/lib/time";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { EmptyState } from "@/shared/ui/page";
import { SelectField } from "@/shared/ui/select-field";
import { Skeleton } from "@/shared/ui/skeleton";
import type { TokensView } from "../model/list-view";
import { isExpired, type Token } from "../model/token";

const date = new Intl.DateTimeFormat(UI_LOCALE, { dateStyle: "medium" });
const when = (iso: string) => date.format(new Date(iso));

/** Sorting is done by the API; the table holds the sort state the URL gives it. */
const columnDefs: ColumnDef<Token>[] = [
  { accessorKey: "name" },
  { accessorKey: "created_at" },
  { accessorKey: "expires_at" },
  { accessorKey: "last_used_at" },
];
const DEFAULT_SORT = "-created_at";
const sortingOf = (sort: string | undefined): SortingState => {
  const spec = sort ?? DEFAULT_SORT;
  return [{ id: spec.replace(/^-/, ""), desc: spec.startsWith("-") }];
};
const specOf = ([first]: SortingState) =>
  first ? `${first.desc ? "-" : ""}${first.id}` : undefined;

interface TokenListProps {
  tokens: readonly Token[];
  view: TokensView;
  onView: (view: TokensView) => void;
  total: number;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  onRevoke: (token: Token) => void;
}

export function TokenList({
  tokens,
  view,
  onView,
  total,
  hasMore,
  loadingMore,
  onLoadMore,
  onRevoke,
}: TokenListProps) {
  const id = useId();
  const [text, setText] = useState(view.q ?? "");
  const commit = useEffectEvent((value: string) => {
    if ((view.q ?? "") !== value.trim()) onView({ ...view, q: value.trim() || undefined });
  });
  // Typing waits a moment before it asks the server.
  useEffect(() => {
    const t = setTimeout(() => commit(text), 300);
    return () => clearTimeout(t);
  }, [text]);
  const table = useReactTable({
    data: tokens as Token[],
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (token) => token.id,
    manualSorting: true,
    manualFiltering: true,
    state: { sorting: sortingOf(view.sort) },
    onSortingChange: (updater) => {
      const next = typeof updater === "function" ? updater(sortingOf(view.sort)) : updater;
      const spec = specOf(next);
      onView({ ...view, sort: spec === DEFAULT_SORT ? undefined : spec });
    },
  });
  return (
    <div>
      <search className="mb-4 flex flex-wrap items-end gap-3">
        <div className="flex min-w-0 flex-1 basis-60 flex-col gap-2">
          <label htmlFor={`${id}-q`} className="text-body font-medium">
            Find a token
          </label>
          <Input
            id={`${id}-q`}
            type="search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Name"
          />
        </div>
        <div className="w-52">
          <SelectField
            id={`${id}-sort`}
            label="Sort by"
            value={specOf(table.getState().sorting)}
            onChange={(e) => table.setSorting(sortingOf(e.target.value))}
          >
            <option value="-created_at">Newest first</option>
            <option value="created_at">Oldest first</option>
            <option value="name">Name, A to Z</option>
            <option value="-name">Name, Z to A</option>
            <option value="-last_used_at">Recently used</option>
            <option value="expires_at">No expiry, then soonest</option>
          </SelectField>
        </div>
      </search>
      {tokens.length === 0 ? (
        <EmptyState title="No tokens match" className="max-w-2xl">
          <p>No token name contains “{view.q}”.</p>
          <Button
            variant="ghost"
            className="mt-3"
            onClick={() => {
              setText("");
              onView({ sort: view.sort });
            }}
          >
            Clear search
          </Button>
        </EmptyState>
      ) : (
        <>
          <ul aria-label="API tokens" className="divide-y divide-rule border-y border-border">
            {table.getRowModel().rows.map(({ original: token }) => {
              const expired = isExpired(token);
              return (
                <li key={token.id} className="row-in flex items-start justify-between gap-3 py-4">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span
                        className={cn(
                          "font-medium [overflow-wrap:anywhere]",
                          expired && "text-muted-foreground",
                        )}
                      >
                        {token.name}
                      </span>
                      <code className="font-mono text-small text-muted-foreground">
                        {token.prefix}…
                      </code>
                    </p>
                    <p className="mt-0.5 text-small text-muted-foreground [overflow-wrap:anywhere]">
                      {token.library_ids == null
                        ? "All libraries you can access"
                        : token.library_ids.length === 0
                          ? "No libraries"
                          : token.library_ids.join(", ")}
                    </p>
                    <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-small text-muted-foreground tabular-nums">
                      <span>Created {when(token.created_at)}</span>
                      <span className={expired ? "font-medium text-destructive" : undefined}>
                        {token.expires_at
                          ? expired
                            ? `Expired ${when(token.expires_at)}`
                            : `Expires ${when(token.expires_at)}`
                          : "No expiry"}
                      </span>
                      <span>
                        {token.last_used_at
                          ? `Last used ${when(token.last_used_at)}`
                          : "Never used"}
                      </span>
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="shrink-0 text-destructive hover:bg-destructive-soft"
                    aria-label={`Revoke ${token.name}`}
                    onClick={() => onRevoke(token)}
                  >
                    Revoke
                  </Button>
                </li>
              );
            })}
            {loadingMore && (
              <li aria-hidden="true" className="py-4">
                <Skeleton className="h-12 w-full" />
              </li>
            )}
          </ul>
          <div className="flex items-center gap-3 pt-4 text-small text-muted-foreground">
            <p className="num">
              Showing {tokens.length} of {total}
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
