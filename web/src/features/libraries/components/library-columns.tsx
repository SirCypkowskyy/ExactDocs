import type { ColumnDef } from "@tanstack/react-table";
import { Pin } from "lucide-react";
import { PHONE_QUERY, useMediaQuery } from "@/shared/lib/use-media-query";
import {
  Count,
  LibraryCell,
  RelativeTime,
  STATE_LOOKS,
  VersionCell,
} from "@/shared/ui/data-table/cells";
import type { TableFilter } from "@/shared/ui/data-table/use-data-table";
import { Tooltip } from "@/shared/ui/tooltip";
import type { listMessages } from "../messages/list";
import type { Library } from "../model/library";
import { AI_CHOICES, IMPORTED_WITHIN, SYNC_STATES, VERSION_CHOICES } from "../model/list-view";
import { SyncCell } from "./sync-status";

/** The libraries table's columns and filters (blocks-map §2.3, "Libraries"). */

type ListMessages = (typeof listMessages)["en"];

/** The version `/owner/repo` resolves to, its commit, and a pin when an owner chose it. */
function DefaultVersion({ library, t }: { library: Library; t: ListMessages["row"] }) {
  const version = library.default_version;
  const sha = library.refs.find((r) => r.ref === version)?.commit_sha;
  if (!version) return <span className="text-muted-foreground">–</span>;
  return (
    <span className="inline-flex min-w-0 items-start gap-1.5">
      <VersionCell version={version} sha={sha} isDefault />
      {library.default_pinned && (
        <Tooltip label={t.pinnedDefaultVersion}>
          <span className="mt-0.5 text-muted-foreground">
            <Pin aria-hidden="true" className="size-3.5" />
            <span className="sr-only">{t.pinnedDefault}</span>
          </span>
        </Tooltip>
      )}
    </span>
  );
}

/** The default version's articles: a figure under the header, "120 articles" on a phone card. */
function Articles({ value, t }: { value: number; t: ListMessages["row"] }) {
  const phone = useMediaQuery(PHONE_QUERY);
  if (phone) return <span className="num">{t.articles(value)}</span>;
  return <Count value={value} muted={value === 0} />;
}

// Built once per language: a cell is rendered as a component, so a new function would remount it.
export const columnsOf = (t: ListMessages): ColumnDef<Library>[] => [
  {
    accessorKey: "title",
    header: t.columns.library,
    enableHiding: false,
    meta: { priority: 1, skeleton: "avatar" },
    cell: ({ row }) => (
      <LibraryCell
        id={row.original.id}
        title={row.original.title}
        description={row.original.description}
        logo={row.original.logo}
        size="md"
      />
    ),
  },
  {
    id: "default_version",
    header: t.columns.defaultVersion,
    enableSorting: false,
    meta: { priority: 2, skeleton: "mono", label: t.columns.defaultVersion },
    cell: ({ row }) => <DefaultVersion library={row.original} t={t.row} />,
  },
  {
    accessorKey: "version_count",
    header: t.columns.versions,
    sortDescFirst: true,
    meta: { align: "end", skeleton: "number", className: "max-lg:hidden" },
    cell: ({ row }) => <Count value={row.original.version_count} />,
  },
  {
    // The default version's articles (#513); not a sort field of `GET /libraries`.
    accessorKey: "article_count",
    header: t.columns.articles,
    enableSorting: false,
    meta: { priority: 3, align: "end", skeleton: "number", className: "max-lg:hidden" },
    cell: ({ row }) => <Articles value={row.original.article_count} t={t.row} />,
  },
  {
    accessorKey: "last_imported_at",
    header: t.columns.lastImported,
    sortDescFirst: true,
    meta: { priority: 3, label: t.columns.lastImported },
    cell: ({ row }) => <RelativeTime iso={row.original.last_imported_at} />,
  },
  {
    id: "sync",
    header: t.columns.sync,
    enableSorting: false,
    enableHiding: false,
    meta: { priority: 2, skeleton: "pill" },
    cell: ({ row }) => <SyncCell library={row.original.id} />,
  },
];

export const filtersOf = (t: ListMessages): TableFilter[] => [
  {
    id: "ai",
    title: t.toolbar.ai,
    single: true,
    options: AI_CHOICES.map((v) => ({
      value: v,
      label: v === "on" ? t.toolbar.aiOn : t.toolbar.aiOff,
    })),
  },
  {
    id: "versions",
    title: t.columns.versions,
    single: true,
    options: VERSION_CHOICES.map((v) => ({ value: v, label: t.toolbar.versions[v] })),
  },
  {
    id: "imported",
    title: t.columns.lastImported,
    single: true,
    options: IMPORTED_WITHIN.map((v) => ({ value: v, label: t.toolbar.within[v] })),
  },
  {
    // The server's filter on each library's latest sync (`sync_state`); the badge shows the same.
    id: "sync",
    title: t.columns.sync,
    options: SYNC_STATES.map((s) => ({
      value: s,
      label: t.toolbar.syncStates[s],
      ...(STATE_LOOKS[s] && { icon: STATE_LOOKS[s].icon }),
    })),
  },
];
