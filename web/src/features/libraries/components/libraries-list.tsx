import { Link, useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Copy, LibraryBig, Pin } from "lucide-react";
import { useId } from "react";
import { toast } from "sonner";
import { common, useMessages } from "@/shared/lib/i18n";
import { useFlash } from "@/shared/lib/use-flash";
import { cn } from "@/shared/lib/utils";
import { IconButton } from "@/shared/ui/button";
import { Count, RelativeTime, VersionCell } from "@/shared/ui/data-table/cells";
import type { TableFilter } from "@/shared/ui/data-table/use-data-table";
import { LibraryMark } from "@/shared/ui/library-mark";
import { EmptyState } from "@/shared/ui/page";
import { codeWell } from "@/shared/ui/recipes";
import { SelectField } from "@/shared/ui/select-field";
import { Tooltip } from "@/shared/ui/tooltip";
import { listMessages } from "../messages/list";
import type { Library } from "../model/library";
import { AI_CHOICES, IMPORTED_WITHIN, type ListView, VERSION_CHOICES } from "../model/list-view";
import { AddLibraryLink } from "./add-library-link";
import { SyncCell } from "./sync-status";

/*
 * The libraries table's parts (blocks-map §2.3, "Libraries"): its columns, its filters, the sort
 * picker phones get instead of headers, and the first-run screen of an instance with none.
 */

type ListMessages = (typeof listMessages)["en"];

/** The library: its mark, its title (or ID) linking to it, the mono ID, and from `lg` one line of its description. */
function LibraryName({ library }: { library: Library }) {
  const [, owner = "", repo = ""] = library.id.split("/");
  return (
    <span className="flex min-w-0 items-start gap-3">
      {/* #504: `logo` once the API sends one. */}
      <LibraryMark id={library.id} size="md" className="mt-0.5" />
      <span className="flex min-w-0 flex-col">
        <Link
          to="/libraries/$owner/$repo"
          params={{ owner, repo }}
          className="w-fit rounded font-medium underline-offset-2 [overflow-wrap:anywhere] outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
        >
          {library.title || library.id}
        </Link>
        {library.title && (
          <span className="font-mono text-small text-muted-foreground [overflow-wrap:anywhere]">
            {library.id}
          </span>
        )}
        {library.description && (
          <span className="max-w-[48ch] truncate text-small text-muted-foreground max-lg:hidden">
            {library.description}
          </span>
        )}
      </span>
    </span>
  );
}

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

// Built once per language: a cell is rendered as a component, so a new function would remount it.
export const columnsOf = (t: ListMessages): ColumnDef<Library>[] => [
  {
    accessorKey: "title",
    header: t.columns.library,
    enableHiding: false,
    meta: { priority: 1, skeleton: "avatar" },
    cell: ({ row }) => <LibraryName library={row.original} />,
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
];

const SORTS = [
  "title",
  "-title",
  "-last_imported_at",
  "last_imported_at",
  "-version_count",
  "version_count",
] as const;

/** Phones get rows as cards, without sortable headers: the order is picked here instead. */
export function PhoneSort({ view }: { view: ListView }) {
  const t = useMessages(listMessages).toolbar;
  const id = useId();
  const navigate = useNavigate();
  const names: Record<(typeof SORTS)[number], string> = {
    title: t.nameAsc,
    "-title": t.nameDesc,
    "-last_imported_at": t.recentlyImported,
    last_imported_at: t.leastRecentlyImported,
    "-version_count": t.mostVersions,
    version_count: t.fewestVersions,
  };
  return (
    <div className="w-full md:hidden">
      <SelectField
        id={`${id}-sort`}
        label={t.sortBy}
        value={view.sort ?? ""}
        onChange={(e) => {
          const sort = e.target.value || undefined;
          void navigate({
            search: (prev: Record<string, unknown>) => ({ ...prev, sort, page: undefined }),
            replace: true,
            resetScroll: false,
          } as never);
        }}
      >
        <option value="">{t.sortDefault}</option>
        {SORTS.map((s) => (
          <option key={s} value={s}>
            {names[s]}
          </option>
        ))}
      </SelectField>
    </div>
  );
}

const COMMAND = "exactdocs add https://github.com/acme/payments --path docs/";

/** An instance with no library yet: what a library is, and the two ways to add one. */
export function FirstRun() {
  const t = useMessages(listMessages).firstRun;
  const c = useMessages(common);
  const [copied, flash] = useFlash(2000);
  const copy = () => {
    void navigator.clipboard?.writeText(COMMAND).then(() => {
      flash();
      toast.success(t.commandCopied);
    });
  };
  return (
    <EmptyState
      icon={<LibraryBig aria-hidden="true" className="size-8!" strokeWidth={1.5} />}
      title={t.title}
      action={<AddLibraryLink />}
      className="max-w-2xl"
    >
      <p>{t.intro}</p>
      <p className="mt-4">{t.commandLine}</p>
      <div className="mt-2 flex items-start gap-1">
        <pre className={cn(codeWell, "min-w-0 flex-1 whitespace-pre-wrap")}>
          <code>{COMMAND}</code>
        </pre>
        <IconButton label={copied ? c.copied : t.copyCommand} done={copied} onClick={copy}>
          <Copy aria-hidden="true" data-icon-motion="pop" />
        </IconButton>
      </div>
    </EmptyState>
  );
}
