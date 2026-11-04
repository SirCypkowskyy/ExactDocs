import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  articleQueryOptions,
  articlesPageQueryOptions,
  type VersionArgs,
} from "../api/browse-queries";
import { type ArticleSummary, ancestorsOf, buildRows, parseTags } from "../model/browse";

/** What the listings of one folder (`""` is the whole version) say so far. */
interface Scope {
  /** `loading`: the first page is on its way; `paging`: a later page is. */
  status: "loading" | "paging" | "idle" | "error";
  /** `null`: everything under the folder is listed; a string: the cursor of the next page. */
  next: string | null | undefined;
  /** The last path listed so far: listings are sorted by path (plain code-point order). */
  last: string | undefined;
  /** Whether a page has arrived (a failed first page leaves the folder without rows). */
  hasData: boolean;
}

interface PageResult {
  data: { articles: readonly ArticleSummary[]; next_cursor: string | null } | undefined;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
}

function scopeOf(pages: readonly PageResult[]): Scope {
  const first = pages[0];
  const last = pages.at(-1);
  const tail = [...pages]
    .reverse()
    .find((p) => p.data)
    ?.data?.articles.at(-1)?.path;
  const status = first?.isLoading
    ? "loading"
    : last?.isError
      ? "error"
      : last?.isFetching && !last.data
        ? "paging"
        : "idle";
  return { status, next: last?.data?.next_cursor, last: tail, hasData: pages.some((p) => p.data) };
}

interface Merged {
  scopes: Record<string, Scope>;
  articles: ArticleSummary[];
}

/**
 * Group the page results by folder (`scopes[i]` names the folder of result `i`) and merge the
 * articles. A query that is switched off and has nothing says nothing about its folder.
 */
function merge(results: readonly PageResult[], scopes: readonly string[]): Merged {
  const byScope = new Map<string, PageResult[]>();
  const articles = new Map<string, ArticleSummary>();
  results.forEach((result, i) => {
    if (!result.data && !result.isFetching && !result.isError) return;
    const scope = scopes[i] ?? "";
    byScope.set(scope, [...(byScope.get(scope) ?? []), result]);
    for (const a of result.data?.articles ?? []) articles.set(a.path, a);
  });
  return {
    scopes: Object.fromEntries([...byScope].map(([scope, pages]) => [scope, scopeOf(pages)])),
    articles: [...articles.values()],
  };
}

const mergeRoot = (results: readonly PageResult[]) =>
  merge(
    results,
    results.map(() => ""),
  );

/** Whether the root listing has already run past a folder: it is sorted, so a folder is contiguous. */
function passedBy(root: Scope | undefined, folder: string): boolean {
  const last = root?.last;
  if (!last || folder === "") return false;
  // Plain code-point comparison, the order the API sorts by.
  return !last.startsWith(`${folder}/`) && last > `${folder}/`;
}

interface TreeArgs extends VersionArgs {
  /** The `tags` search param (comma-separated), so the hook's identity only changes with it. */
  tags: string | undefined;
  /** The open article: its folders start expanded and it is shown even when paging has not reached it. */
  selected: string | undefined;
}

const none: readonly string[] = [];

/**
 * The lazily loaded tree of one version (and tag filter). Every page is an observed query, so the
 * Query cache is the only copy: it refetches and expires as usual. The version's listing loads on
 * mount, a folder's when it is first expanded, and a listing's next page on request.
 */
export function useTree({ owner, repo, ref, sha, tags: tagsParam, selected }: TreeArgs) {
  const queryClient = useQueryClient();
  const tags = useMemo(() => parseTags(tagsParam), [tagsParam]);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(
    () => new Set(selected ? ancestorsOf(selected) : []),
  );
  // The cursors of the later pages the reader asked for, per folder, in order.
  const [more, setMore] = useState<Readonly<Record<string, readonly string[]>>>({});

  // The article's folders open when the URL moves to another folder.
  useEffect(() => {
    if (!selected) return;
    setExpanded((prev) => {
      const missing = ancestorsOf(selected).filter((f) => !prev.has(f));
      return missing.length ? new Set([...prev, ...missing]) : prev;
    });
  }, [selected]);

  const pageOptions = useCallback(
    (prefix: string, cursor: string | undefined) =>
      articlesPageQueryOptions({ owner, repo, ref, sha, tags, prefix, cursor }),
    [owner, repo, ref, sha, tags],
  );

  const root = useQueries({
    queries: [undefined, ...(more[""] ?? none)].map((cursor) => pageOptions("", cursor)),
    combine: mergeRoot,
  });

  // A folder is listed on its own once opened, unless the root listing has already run past it.
  const folders = [...expanded].filter((f) => !passedBy(root.scopes[""], f)).sort();
  const requests = folders.flatMap((folder) =>
    [undefined, ...(more[folder] ?? none)].map((cursor) => ({ folder, cursor })),
  );
  const ownersKey = JSON.stringify(requests.map((q) => q.folder));
  const rootDone = root.scopes[""]?.status !== "loading";
  const own = useQueries({
    queries: requests.map(({ folder, cursor }) => ({
      ...pageOptions(folder, cursor),
      enabled: rootDone && !(root.scopes[""]?.next === null),
    })),
    combine: useCallback(
      (r: readonly PageResult[]) => merge(r, JSON.parse(ownersKey)),
      [ownersKey],
    ),
  });

  const scopes = useMemo(() => ({ ...own.scopes, ...root.scopes }), [own.scopes, root.scopes]);
  const complete = useCallback(
    (folder: string) =>
      passedBy(scopes[""], folder) ||
      [...ancestorsOf(`${folder}/_`), ""].some(
        (f) => scopes[f]?.status === "idle" && scopes[f]?.next === null,
      ),
    [scopes],
  );

  // The open article is shown even when paging has not reached it (it is the same query the
  // article pane runs, so this costs nothing extra).
  const listed = useMemo(
    () => new Set([...root.articles, ...own.articles].map((a) => a.path)),
    [root.articles, own.articles],
  );
  const parentScope = selected ? scopes[selected.split("/").slice(0, -1).join("/")] : undefined;
  const needsSelected =
    selected !== undefined &&
    tags.length === 0 &&
    !listed.has(selected) &&
    (parentScope?.hasData ?? false);
  const opened = useQuery({
    ...articleQueryOptions({ owner, repo, ref, sha }, selected ?? ""),
    enabled: needsSelected,
  });

  const articles = useMemo(() => {
    const all = new Map<string, ArticleSummary>();
    for (const a of [...root.articles, ...own.articles]) all.set(a.path, a);
    const a = opened.data;
    if (needsSelected && a)
      all.set(a.path, { path: a.path, title: a.title, tags: a.tags, size: a.size });
    return [...all.values()];
  }, [root.articles, own.articles, opened.data, needsSelected]);

  const rows = useMemo(() => {
    const partial = new Set<string>();
    const loading = new Set<string>();
    const failed = new Set<string>();
    for (const [folder, scope] of Object.entries(scopes)) {
      if (scope.status === "loading") loading.add(folder);
      if (scope.status === "error") failed.add(folder);
      if (scope.status === "error" || (typeof scope.next === "string" && !complete(folder)))
        partial.add(folder);
    }
    return buildRows(articles, expanded, partial, loading, failed);
  }, [articles, expanded, scopes, complete]);

  const toggle = useCallback((folder: string, open?: boolean) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (open ?? !prev.has(folder)) next.add(folder);
      else next.delete(folder);
      return next;
    });
  }, []);

  /** Ask for the next page of a folder's listing, or try the page that failed again. */
  const loadMore = useCallback(
    (scope: string) => {
      const info = scopes[scope];
      if (!info) return;
      const cursors = [undefined, ...(more[scope] ?? none)];
      if (info.status === "error") {
        void queryClient.refetchQueries({ queryKey: pageOptions(scope, cursors.at(-1)).queryKey });
      } else if (typeof info.next === "string" && info.status === "idle") {
        const next = info.next;
        setMore((m) => ({ ...m, [scope]: [...(m[scope] ?? none), next] }));
      }
    },
    [scopes, more, pageOptions, queryClient],
  );

  const status =
    scopes[""]?.status === "loading" || !scopes[""]
      ? "loading"
      : scopes[""]?.status === "error" && !scopes[""]?.hasData
        ? "error"
        : "ready";

  return { rows, status, toggle, loadMore, scopes } as const;
}
