import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { useId, useMemo } from "react";
import { parseTags } from "@/shared/lib/tags";
import { usePrefetchedPages } from "@/shared/lib/use-prefetched-pages";
import {
  ColumnsMenu,
  DataTable,
  ListFooter,
  SearchFilter,
  useServerTable,
} from "@/shared/ui/data-table";
import { articlesTableQueryOptions } from "../api/browse-queries";
import type { ArticleSummary, BrowseSearch } from "../model/browse";

interface Props {
  owner: string;
  repo: string;
  /** The version's ref and commit. */
  versionRef: string;
  sha: string;
  search: BrowseSearch;
}

const sizeOf = (bytes: number) =>
  bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(bytes < 10_240 ? 1 : 0)} KB`;

/** Every article of the version as a table, sorted and filtered by the server (path, title, tags). */
export function ArticlesTable({ owner, repo, versionRef, sha, search }: Props) {
  const navigate = useNavigate();
  const onView = (next: Pick<BrowseSearch, "filter" | "sort">) =>
    void navigate({
      to: "/libraries/$owner/$repo",
      params: { owner, repo },
      search: (prev) => ({ ...prev, ...next }),
      replace: true,
    });
  const tags = useMemo(() => parseTags(search.tags), [search.tags]);
  const view = { tags: search.tags, filter: search.filter, sort: search.sort };
  const query = useInfiniteQuery(
    articlesTableQueryOptions({
      owner,
      repo,
      ref: versionRef,
      sha,
      tags,
      filter: search.filter,
      sort: search.sort,
    }),
  );
  const { pages, hasMore, loadingMore, loadMore } = usePrefetchedPages(query, view);
  const articles = pages.flatMap((p) => p.articles);
  const id = useId();
  const version = search.version;
  const tagsParam = search.tags;
  // Stable while the page shows this version and tags: a new cell function remounts its rows.
  const columns = useMemo<ColumnDef<ArticleSummary>[]>(
    () => [
      {
        accessorKey: "path",
        header: "Path",
        enableHiding: false,
        cell: ({ row }) => (
          <Link
            to="/libraries/$owner/$repo"
            params={{ owner, repo }}
            search={{ version, path: row.original.path, tags: tagsParam }}
            className="rounded font-mono text-mono [overflow-wrap:anywhere] underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
          >
            {row.original.path}
          </Link>
        ),
      },
      { accessorKey: "title", header: "Title", meta: { className: "max-md:hidden" } },
      {
        accessorKey: "tags",
        header: "Tags",
        enableSorting: false,
        meta: { className: "max-lg:hidden" },
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.tags.join(", ")}</span>
        ),
      },
      {
        accessorKey: "size",
        header: "Size",
        sortDescFirst: true,
        meta: { className: "num whitespace-nowrap" },
        cell: ({ row }) => sizeOf(row.original.size),
      },
    ],
    [owner, repo, version, tagsParam],
  );
  const table = useServerTable({
    data: articles,
    columns,
    getRowId: (a) => a.path,
    sort: search.sort,
    onSort: (sort) => onView({ sort }),
  });

  return (
    <section aria-labelledby={`${id}-h`} className="mt-8 border-t border-rule pt-5">
      <h2 id={`${id}-h`} className="text-section font-semibold">
        Articles
      </h2>
      <search className="mt-3 mb-3 flex flex-wrap items-end gap-3">
        <SearchFilter
          id={`${id}-q`}
          label="Find an article"
          placeholder="Path or title"
          value={search.filter}
          onCommit={(filter) => onView({ filter })}
        />
        <ColumnsMenu table={table} />
      </search>
      {query.isError && !query.data ? (
        <p role="alert">
          Couldn't load articles.{" "}
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="cursor-pointer font-medium underline"
          >
            Retry
          </button>
        </p>
      ) : query.data && articles.length === 0 ? (
        <p className="rounded-lg border border-dashed border-input px-4 py-5 text-body text-muted-foreground">
          {search.filter || tags.length ? "No articles match these filters." : "No articles."}
        </p>
      ) : (
        <>
          <DataTable table={table} label="Articles" loadingMore={loadingMore || query.isPending} />
          {query.data && (
            <ListFooter
              shown={articles.length}
              // An older server sends no total; what is shown is then all that is known.
              total={pages.at(-1)?.total ?? articles.length}
              hasMore={hasMore}
              loadingMore={loadingMore}
              onLoadMore={loadMore}
            />
          )}
        </>
      )}
    </section>
  );
}
