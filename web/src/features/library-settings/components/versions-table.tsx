import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { ArrowRight, Copy, GitBranch, Pin, Trash2 } from "lucide-react";
import { useMemo } from "react";
import { toast } from "sonner";
import { useMessages } from "@/shared/lib/i18n";
import { useNow } from "@/shared/lib/use-now";
import { Badge } from "@/shared/ui/badge";
import { MonoCopy, RelativeTime } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import type { RowAction } from "@/shared/ui/data-table/row-actions";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import { type TableFilter, useDataTable } from "@/shared/ui/data-table/use-data-table";
import { VersionStation } from "@/shared/ui/route";
import { libraryRetrievalQueryOptions } from "../api/retrieval";
import { versionsSource } from "../api/settings";
import { versionsMessages } from "../messages/versions";
import type { LibraryRetrieval } from "../model/retrieval";
import type { ListedVersion, SettingsVersion } from "../model/settings";
import {
  IMPORTED_WITHIN,
  parseVersionsView,
  REF_KINDS,
  VERSION_ORIGINS,
  VERSIONS_TABLE,
} from "../model/versions-view";
import { ArticlesCell, EmbeddingCell, type NoEmbedding } from "./version-counts";

/*
 * The library's versions (blocks-map §2.3, "Versions") on DataTable v2: numbered pages sorted and
 * filtered by the server, the view in the settings URL, row actions in a kebab and a context menu.
 */

interface Props {
  owner: string;
  repo: string;
  /** An owner pinned the default version: its row says so. */
  pinned: boolean;
  onRemove: (version: SettingsVersion) => void;
}

type Texts = (typeof versionsMessages)["en"]["table"];

/** A kind or origin the API sends, by its name; one this client does not know shows as sent. */
const nameOf = (names: Readonly<Record<string, string>>, value: string) => names[value] ?? value;

function VersionName({ v, pinned, t }: { v: SettingsVersion; pinned: boolean; t: Texts }) {
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
      <VersionStation
        version={v.ref}
        isDefault={v.is_default}
        className="text-body [&_span:last-child]:text-body [&_span:last-child]:[overflow-wrap:anywhere]"
      />
      {v.is_default && (
        <span className="inline-flex items-center gap-1.5 text-small font-medium text-route">
          {t.default}
          {pinned && (
            <span className="inline-flex items-center gap-1 font-normal text-muted-foreground">
              <Pin aria-hidden="true" className="size-3" />
              {t.pinned}
            </span>
          )}
        </span>
      )}
    </span>
  );
}

/**
 * Why nothing of the library is embedded, from its retrieval settings (the AI section reads them
 * too, so this costs no request): AI off for it, or no embedding model on the instance. Undefined
 * while they are unknown (loading, or not readable by this caller): the meter then says "0 of N".
 */
function noEmbeddingOf(retrieval: LibraryRetrieval | undefined): NoEmbedding | undefined {
  if (!retrieval) return undefined;
  if (!retrieval.ai_enabled) return "aiOff";
  return retrieval.configured_roles.includes("embedding") ? undefined : "noModel";
}

// Built once per language, pin state and embedding state: a cell is rendered as a component, so a
// new function would remount it.
const columnsOf = (
  t: Texts,
  pinned: boolean,
  none: NoEmbedding | undefined,
): ColumnDef<ListedVersion>[] => [
  {
    accessorKey: "ref",
    header: t.columns.version,
    enableHiding: false,
    meta: { priority: 1, skeleton: "mono" },
    cell: ({ row }) => <VersionName v={row.original} pinned={pinned} t={t} />,
  },
  {
    accessorKey: "kind",
    header: t.columns.kind,
    meta: { priority: 2, skeleton: "pill" },
    cell: ({ row }) => <Badge>{nameOf(t.kinds, row.original.kind)}</Badge>,
  },
  {
    accessorKey: "commit_sha",
    header: t.columns.commit,
    enableSorting: false,
    meta: { skeleton: "mono", className: "max-xl:hidden" },
    cell: ({ row }) => (
      <MonoCopy
        value={row.original.commit_sha}
        display={row.original.commit_sha.slice(0, 7)}
        what={t.commitWhat}
      />
    ),
  },
  {
    accessorKey: "origin",
    header: t.columns.origin,
    meta: { className: "max-xl:hidden" },
    cell: ({ row }) => (
      <span className="text-muted-foreground">{nameOf(t.origins, row.original.origin)}</span>
    ),
  },
  {
    accessorKey: "imported_at",
    header: t.columns.imported,
    sortDescFirst: true,
    meta: { priority: 3 },
    cell: ({ row }) => <RelativeTime iso={row.original.imported_at} />,
  },
  {
    // Neither count is a sort field of `GET .../versions`.
    accessorKey: "articles",
    header: t.columns.articles,
    enableSorting: false,
    meta: { priority: 3, align: "end", skeleton: "number", className: "max-lg:hidden" },
    cell: ({ row }) => <ArticlesCell value={row.original.articles} t={t} />,
  },
  {
    id: "embedding",
    header: t.columns.embedding,
    enableSorting: false,
    meta: {
      priority: 3,
      skeleton: "meter",
      label: t.columns.embedding,
      className: "max-lg:hidden",
    },
    cell: ({ row }) => (
      <EmbeddingCell
        embedded={row.original.embedded_chunks}
        chunks={row.original.chunks}
        none={none}
        t={t}
      />
    ),
  },
];

const filtersOf = (t: Texts): TableFilter[] => [
  { id: "kind", title: t.kind, options: REF_KINDS.map((k) => ({ value: k, label: t.kinds[k] })) },
  {
    id: "origin",
    title: t.origin,
    options: VERSION_ORIGINS.map((o) => ({ value: o, label: t.origins[o] })),
  },
  {
    id: "imported",
    title: t.imported,
    single: true,
    options: IMPORTED_WITHIN.map((w) => ({ value: w, label: t.within[w] })),
  },
];

/** The library's versions, sorted, filtered and paged by the server; the view lives in the settings URL. */
export function VersionsTable({ owner, repo, pinned, onRemove }: Props) {
  const t = useMessages(versionsMessages).table;
  const view = parseVersionsView(useSearch({ strict: false }) as Record<string, unknown>);
  const navigate = useNavigate();
  const now = useNow();
  const none = noEmbeddingOf(useQuery(libraryRetrievalQueryOptions(owner, repo)).data);
  const columns = useMemo(() => columnsOf(t, pinned, none), [t, pinned, none]);
  const filters = useMemo(() => filtersOf(t), [t]);
  const model = useDataTable({
    config: VERSIONS_TABLE,
    search: view,
    columns,
    getRowId: (v) => v.ref,
    filters,
    source: versionsSource(owner, repo, view, now),
  });

  const actions = (v: ListedVersion): RowAction<ListedVersion>[] => [
    {
      id: "browse",
      label: t.actions.browse,
      icon: ArrowRight,
      motion: "forward",
      onSelect: () =>
        void navigate({
          to: "/libraries/$owner/$repo",
          params: { owner, repo },
          search: { version: v.ref },
        }),
    },
    {
      id: "copy-commit",
      label: t.actions.copyCommit,
      icon: Copy,
      motion: "pop",
      onSelect: () => {
        void navigator.clipboard?.writeText(v.commit_sha).then(
          () => toast.success(t.actions.copied),
          () => {},
        );
      },
    },
    {
      id: "remove",
      label: t.actions.remove,
      icon: Trash2,
      motion: "warn",
      destructive: true,
      group: true,
      onSelect: onRemove,
    },
  ];

  return (
    <>
      <DataTableToolbar model={model} search={{ label: t.find, placeholder: t.findPlaceholder }} />
      <DataTable
        model={model}
        label={t.label}
        rowActions={actions}
        rowLabel={(v) => v.ref}
        empty={{ icon: GitBranch, title: t.empty }}
        noMatch={{ title: t.noMatch, body: t.noMatchBody }}
        errorMessage={t.loadFailed}
      />
      <DataTablePagination model={model} />
    </>
  );
}
