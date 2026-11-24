import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useRouter } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { ArrowRight, ArrowUpRight, Copy, FileText, FolderOpen, Link2 } from "lucide-react";
import { useId, useMemo } from "react";
import { toast } from "sonner";
import { useMessages } from "@/shared/lib/i18n";
import { tagsQueryOptions } from "@/shared/lib/tags-query";
import { Bytes, Chips } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import type { RowAction } from "@/shared/ui/data-table/row-actions";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import {
  type TableFilter,
  type TableParam,
  useDataTable,
} from "@/shared/ui/data-table/use-data-table";
import { Section } from "@/shared/ui/page";
import { articlesSource, type VersionArgs } from "../api/browse-queries";
import { messages } from "../messages";
import { ARTICLES_TABLE, articleFilters, articlesView, folderOf } from "../model/articles-view";
import {
  type ArticleSummary,
  type BrowseSearch,
  hostName,
  type LibraryDetail,
  type Version,
} from "../model/browse";
import { blobUrl } from "../render/urls";

/*
 * Every article of the version (blocks-map §2.3, up to 7,000): numbered pages sorted and filtered
 * by the server, the view in the library page's URL, row actions in a kebab and a context menu.
 */

type TableMessages = (typeof messages)["en"]["table"];

interface Props {
  owner: string;
  repo: string;
  library: LibraryDetail;
  version: Version;
  search: BrowseSearch;
}

/** Tags shown in a row before "+N". */
const SHOWN_TAGS = 3;

/** The folder muted, the file name in ink; the link's name is the whole path. */
function PathText({ path }: { path: string }) {
  const folder = folderOf(path);
  return (
    <>
      {folder && <span className="text-muted-foreground">{folder}/</span>}
      {folder ? path.slice(folder.length + 1) : path}
    </>
  );
}

/** Where a row's link goes: the reader, in the version and tag filter the page shows. */
interface Target {
  owner: string;
  repo: string;
  version: string | undefined;
  tags: string | undefined;
}

// Built once per language and page: a cell is rendered as a component, so a new function would
// remount it.
const columnsOf = (t: TableMessages, to: Target): ColumnDef<ArticleSummary>[] => [
  {
    accessorKey: "path",
    header: t.path,
    enableHiding: false,
    meta: { priority: 1, skeleton: "mono" },
    cell: ({ row }) => (
      <Link
        to="/libraries/$owner/$repo"
        params={{ owner: to.owner, repo: to.repo }}
        search={{ version: to.version, path: row.original.path, tags: to.tags }}
        className="rounded font-mono text-mono [overflow-wrap:anywhere] underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
      >
        <PathText path={row.original.path} />
      </Link>
    ),
  },
  {
    accessorKey: "title",
    header: t.title,
    meta: { priority: 2, className: "max-md:hidden" },
    cell: ({ row }) => <span className="[overflow-wrap:anywhere]">{row.original.title}</span>,
  },
  {
    accessorKey: "tags",
    header: t.tags,
    enableSorting: false,
    meta: { skeleton: "pill", className: "max-lg:hidden" },
    cell: ({ row }) => (
      <Chips
        items={row.original.tags}
        label={t.tags}
        shown={SHOWN_TAGS}
        look="pill"
        more={(n) => t.moreTags(n, row.original.path)}
        title={t.tagsOf(row.original.path)}
      />
    ),
  },
  {
    accessorKey: "size",
    header: t.size,
    sortDescFirst: true,
    meta: { priority: 3, align: "end", skeleton: "number", label: t.size },
    cell: ({ row }) => <Bytes value={row.original.size} />,
  },
];

/** The version's tags as a facet: the counted ones, and any the URL names beyond them. */
function useTagsFilter(
  t: TableMessages,
  at: VersionArgs,
  picked: readonly string[] | undefined,
): TableFilter {
  const counted = useQuery(tagsQueryOptions(at));
  return useMemo(() => {
    const known = (counted.data?.tags ?? []).map((f) => f.tag);
    const seen = new Set(known);
    const values = [...known, ...(picked ?? []).filter((p) => !seen.has(p))];
    return { id: "tags", title: t.tags, options: values.map((v) => ({ value: v, label: v })) };
  }, [counted.data, picked, t]);
}

function copy(text: string, done: string) {
  void navigator.clipboard?.writeText(text).then(
    () => toast.success(done),
    () => {},
  );
}

export function ArticlesTable({ owner, repo, library, version, search }: Props) {
  const t = useMessages(messages).table;
  const id = useId();
  const router = useRouter();
  const navigate = useNavigate();
  const view = useMemo(() => articlesView(search), [search]);
  const at = { owner, repo, ref: version.ref, sha: version.commit_sha };
  const columns = useMemo(
    () => columnsOf(t, { owner, repo, version: search.version, tags: search.tags }),
    [t, owner, repo, search.version, search.tags],
  );
  const tagsFilter = useTagsFilter(t, at, view.tags);
  const filters = useMemo(() => [tagsFilter], [tagsFilter]);
  const params = useMemo<TableParam[]>(() => [{ id: "prefix", title: t.folder, mono: true }], [t]);
  const model = useDataTable({
    config: ARTICLES_TABLE,
    search: view,
    // The page's `q` is the version's search (its results replace this table), so the table's
    // text filter is `filter` in the URL.
    qParam: "filter",
    columns,
    getRowId: (a) => a.path,
    filters,
    params,
    source: articlesSource(at, articleFilters(view)),
  });

  const host = hostName(library.host);
  const actions = (article: ArticleSummary): RowAction<ArticleSummary>[] => {
    const onHost = blobUrl(library.host, library.source_url, version.commit_sha, article.path);
    const folder = folderOf(article.path);
    return [
      {
        id: "open",
        label: t.open,
        icon: ArrowRight,
        motion: "forward",
        onSelect: () =>
          void navigate({
            to: "/libraries/$owner/$repo",
            params: { owner, repo },
            search: { version: search.version, path: article.path, tags: search.tags },
          }),
      },
      {
        id: "copy-path",
        label: t.copyPath,
        icon: Copy,
        motion: "pop",
        onSelect: () => copy(article.path, t.pathCopied),
      },
      {
        id: "copy-link",
        label: t.copyLink,
        icon: Link2,
        motion: "pop",
        onSelect: () => {
          // Pinned to this version's ref, whatever the default becomes later.
          const { href } = router.buildLocation({
            to: "/libraries/$owner/$repo",
            params: { owner, repo },
            search: { version: version.ref, path: article.path },
          });
          copy(new URL(href, window.location.href).href, t.linkCopied);
        },
      },
      ...(onHost
        ? [
            {
              id: "host",
              label: t.openOn(host),
              icon: ArrowUpRight,
              motion: "out" as const,
              onSelect: () => void window.open(onHost, "_blank", "noopener,noreferrer"),
            },
          ]
        : []),
      ...(folder && folder !== search.prefix
        ? [
            {
              id: "folder",
              label: t.inFolder,
              icon: FolderOpen,
              motion: "tilt" as const,
              group: true,
              onSelect: () => model.setParam("prefix", folder),
            },
          ]
        : []),
    ];
  };

  return (
    <Section
      id={`${id}-articles`}
      title={t.articles}
      icon={<FileText />}
      description={model.total !== undefined && <span className="num">{t.count(model.total)}</span>}
      className="mt-8 border-t border-rule pt-5"
    >
      <DataTableToolbar
        model={model}
        search={{ label: t.findArticle, placeholder: t.pathOrTitle }}
      />
      <DataTable
        model={model}
        label={t.articles}
        rowActions={actions}
        rowLabel={(a) => a.path}
        empty={{ icon: FileText, title: t.none }}
        noMatch={{ title: t.noMatch }}
        errorMessage={t.loadFailed}
        // Not the kit's "Try again": the file tree beside it has that one.
        retryLabel={t.retry}
      />
      <DataTablePagination model={model} />
    </Section>
  );
}
