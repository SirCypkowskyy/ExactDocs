import { useInfiniteQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { createContext, use, useId } from "react";
import { common, type Language, useLanguage, useMessages } from "@/shared/lib/i18n";
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
import { sharedMessages } from "../messages/shared";
import { versionsMessages } from "../messages/versions";
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
  const language = useLanguage();
  return (
    <time dateTime={iso} title={absoluteTimeWithZone(iso, language)}>
      {relativeTime(iso, now, language)}
    </time>
  );
}

function RemoveButton({ version }: { version: SettingsVersion }) {
  const onRemove = use(RemoveContext);
  const t = useMessages(versionsMessages).table;
  const { remove } = useMessages(common);
  return (
    <Button
      type="button"
      variant="ghost"
      aria-label={t.remove(version.ref)}
      onClick={(e) => onRemove(version, e.currentTarget)}
      className="-my-2 text-muted-foreground hover:bg-destructive-soft hover:text-destructive focus-visible:text-destructive"
    >
      {remove}
    </Button>
  );
}

/** The columns in one language. Headers are strings: the columns menu and sort labels read them. */
function columnsIn(language: Language): ColumnDef<SettingsVersion>[] {
  const t = versionsMessages[language].table;
  return [
    {
      accessorKey: "ref",
      header: t.columns.version,
      enableHiding: false,
      cell: ({ row: { original: v } }) => (
        <span className="flex flex-wrap items-center gap-x-3">
          <VersionStation
            version={v.ref}
            isDefault={v.is_default}
            className="text-body [&_span:last-child]:text-body [&_span:last-child]:[overflow-wrap:anywhere]"
          />
          {v.is_default && <span className="text-small font-medium text-route">{t.default}</span>}
        </span>
      ),
    },
    {
      accessorKey: "kind",
      header: t.columns.kind,
      meta: { className: "capitalize max-md:hidden" },
      cell: ({ row }) => t.kinds[row.original.kind] ?? row.original.kind,
    },
    {
      accessorKey: "commit_sha",
      header: t.columns.commit,
      enableSorting: false,
      meta: { className: "max-md:hidden" },
      cell: ({ row }) => <Commit sha={row.original.commit_sha} />,
    },
    {
      accessorKey: "origin",
      header: t.columns.origin,
      meta: { className: "max-lg:hidden" },
      cell: ({ row }) => t.origins[row.original.origin] ?? row.original.origin,
    },
    {
      accessorKey: "imported_at",
      header: t.columns.imported,
      sortDescFirst: true,
      cell: ({ row }) => <Imported iso={row.original.imported_at} />,
    },
    {
      id: "actions",
      header: t.columns.actions,
      enableSorting: false,
      enableHiding: false,
      cell: ({ row }) => <RemoveButton version={row.original} />,
    },
  ];
}

// Built once per language on purpose: a cell is rendered as a component, so a new function
// would remount it.
const COLUMNS: Readonly<Record<Language, ColumnDef<SettingsVersion>[]>> = {
  en: columnsIn("en"),
  pl: columnsIn("pl"),
};

/** The library's versions, sorted and filtered by the server; the view lives in the settings URL. */
export function VersionsTable({ owner, repo, onRemove }: Props) {
  const language = useLanguage();
  const t = versionsMessages[language].table;
  const { retry } = sharedMessages[language];
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
    columns: COLUMNS[language],
    getRowId: (v) => v.ref,
    sort: view.sort,
    onSort: (sort) => onView({ ...view, sort }),
  });

  if (query.isError && !query.data) {
    return (
      <p role="alert">
        {t.loadFailed}{" "}
        <button
          type="button"
          onClick={() => void query.refetch()}
          className="cursor-pointer font-medium underline"
        >
          {retry}
        </button>
      </p>
    );
  }
  if (query.data && total === 0 && !versionsFiltered(view)) {
    return (
      <p className="rounded-lg border border-dashed border-input px-4 py-5 text-body text-muted-foreground">
        {t.empty}
      </p>
    );
  }
  return (
    <RemoveContext value={onRemove}>
      <search className="mb-3 flex flex-wrap items-end gap-3">
        <SearchFilter
          id={`${id}-q`}
          label={t.find}
          placeholder={t.findPlaceholder}
          value={view.q}
          onCommit={(q) => onView({ ...view, q })}
        />
        <div className="w-32">
          <SelectField
            id={`${id}-kind`}
            label={t.kind}
            value={view.kind ?? ""}
            onChange={(e) =>
              onView({ ...view, kind: parseVersionsView({ kind: e.target.value }).kind })
            }
          >
            <option value="">{t.any}</option>
            {REF_KINDS.map((k) => (
              <option key={k} value={k}>
                {t.kinds[k]}
              </option>
            ))}
          </SelectField>
        </div>
        <ColumnsMenu table={table} />
      </search>
      {query.data && versions.length === 0 ? (
        <p className="rounded-lg border border-dashed border-input px-4 py-5 text-body text-muted-foreground">
          {t.noMatch}{" "}
          <button
            type="button"
            onClick={() => onView({ sort: view.sort })}
            className="cursor-pointer font-medium text-foreground underline underline-offset-2"
          >
            {t.clearFilters}
          </button>
        </p>
      ) : (
        <>
          <DataTable table={table} label={t.label} loadingMore={loadingMore || query.isPending} />
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
