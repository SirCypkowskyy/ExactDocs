import { useInfiniteQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { createContext, use, useId } from "react";
import { absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { usePrefetchedPages } from "@/shared/lib/use-prefetched-pages";
import { Button } from "@/shared/ui/button";
import {
  ColumnsMenu,
  DataTable,
  ListFooter,
  SearchFilter,
  useServerTable,
} from "@/shared/ui/data-table";
import { Commit, VersionStation } from "@/shared/ui/route";
import { SelectField } from "@/shared/ui/select-field";
import { versionsQueryOptions } from "../api/settings";
import { useNow } from "../hooks/use-now";
import type { SettingsVersion } from "../model/settings";
import {
  parseVersionsView,
  REF_KINDS,
  type VersionsView,
  versionsFiltered,
} from "../model/versions-view";

interface Props {
  owner: string;
  repo: string;
  onRemove: (version: SettingsVersion, trigger: HTMLElement) => void;
}

/** The remove handler of the table the button is in: the columns stay the same between renders. */
const RemoveContext = createContext<Props["onRemove"]>(() => {});

function Imported({ iso }: { iso: string }) {
  const now = useNow();
  return (
    <time dateTime={iso} title={absoluteTimeWithZone(iso)}>
      {relativeTime(iso, now)}
    </time>
  );
}

function RemoveButton({ version }: { version: SettingsVersion }) {
  const onRemove = use(RemoveContext);
  return (
    <Button
      type="button"
      variant="ghost"
      aria-label={`Remove version ${version.ref}`}
      onClick={(e) => onRemove(version, e.currentTarget)}
      className="-my-2 text-muted-foreground hover:bg-destructive-soft hover:text-destructive focus-visible:text-destructive"
    >
      Remove
    </Button>
  );
}

// Module level on purpose: a cell is rendered as a component, so a new function would remount it.
const columns: ColumnDef<SettingsVersion>[] = [
  {
    accessorKey: "ref",
    header: "Version",
    enableHiding: false,
    cell: ({ row: { original: v } }) => (
      <span className="flex flex-wrap items-center gap-x-3">
        <VersionStation
          version={v.ref}
          isDefault={v.is_default}
          className="text-body [&_span:last-child]:text-body [&_span:last-child]:[overflow-wrap:anywhere]"
        />
        {v.is_default && <span className="text-small font-medium text-route">default</span>}
      </span>
    ),
  },
  { accessorKey: "kind", header: "Kind", meta: { className: "capitalize max-md:hidden" } },
  {
    accessorKey: "commit_sha",
    header: "Commit",
    enableSorting: false,
    meta: { className: "max-md:hidden" },
    cell: ({ row }) => <Commit sha={row.original.commit_sha} />,
  },
  { accessorKey: "origin", header: "Origin", meta: { className: "max-lg:hidden" } },
  {
    accessorKey: "imported_at",
    header: "Imported",
    sortDescFirst: true,
    cell: ({ row }) => <Imported iso={row.original.imported_at} />,
  },
  {
    id: "actions",
    header: "Actions",
    enableSorting: false,
    enableHiding: false,
    cell: ({ row }) => <RemoveButton version={row.original} />,
  },
];

/** The library's versions, sorted and filtered by the server; the view lives in the settings URL. */
export function VersionsTable({ owner, repo, onRemove }: Props) {
  const view = parseVersionsView(useSearch({ strict: false }) as Record<string, unknown>);
  const navigate = useNavigate();
  const onView = (next: VersionsView) =>
    void navigate({
      to: "/libraries/$owner/$repo/settings",
      params: { owner, repo },
      search: { ...next },
      hash: "versions",
      replace: true,
    });
  const query = useInfiniteQuery(versionsQueryOptions(owner, repo, view));
  const { pages, hasMore, loadingMore, loadMore } = usePrefetchedPages(query, view);
  const versions = pages.flatMap((p) => p.versions);
  const total = pages.at(-1)?.total ?? 0;
  const id = useId();
  const table = useServerTable({
    data: versions,
    columns,
    getRowId: (v) => v.ref,
    sort: view.sort,
    onSort: (sort) => onView({ ...view, sort }),
  });

  if (query.isError && !query.data) {
    return (
      <p role="alert">
        Couldn't load versions.{" "}
        <button
          type="button"
          onClick={() => void query.refetch()}
          className="cursor-pointer font-medium underline"
        >
          Retry
        </button>
      </p>
    );
  }
  if (query.data && total === 0 && !versionsFiltered(view)) {
    return (
      <p className="rounded-lg border border-dashed border-input px-4 py-5 text-body text-muted-foreground">
        No versions yet. Add one, or wait for the first import to finish.
      </p>
    );
  }
  return (
    <RemoveContext value={onRemove}>
      <search className="mb-3 flex flex-wrap items-end gap-3">
        <SearchFilter
          id={`${id}-q`}
          label="Find a version"
          placeholder="Ref or commit"
          value={view.q}
          onCommit={(q) => onView({ ...view, q })}
        />
        <div className="w-32">
          <SelectField
            id={`${id}-kind`}
            label="Kind"
            value={view.kind ?? ""}
            onChange={(e) =>
              onView({ ...view, kind: parseVersionsView({ kind: e.target.value }).kind })
            }
          >
            <option value="">Any</option>
            {REF_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </SelectField>
        </div>
        <ColumnsMenu table={table} />
      </search>
      {query.data && versions.length === 0 ? (
        <p className="rounded-lg border border-dashed border-input px-4 py-5 text-body text-muted-foreground">
          No versions match.{" "}
          <button
            type="button"
            onClick={() => onView({ sort: view.sort })}
            className="cursor-pointer font-medium text-foreground underline underline-offset-2"
          >
            Clear filters
          </button>
        </p>
      ) : (
        <>
          <DataTable
            table={table}
            label="Imported versions"
            loadingMore={loadingMore || query.isPending}
          />
          {query.data && (
            <ListFooter
              shown={versions.length}
              total={total}
              hasMore={hasMore}
              loadingMore={loadingMore}
              onLoadMore={loadMore}
            />
          )}
        </>
      )}
    </RemoveContext>
  );
}
