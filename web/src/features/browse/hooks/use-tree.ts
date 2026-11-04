import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { articlesPageQueryOptions } from "../api/browse-queries";
import { type ArticleSummary, ancestorsOf, buildRows, parseTags } from "../model/browse";

interface Scope {
  status: "loading" | "idle" | "error";
  /** `null`: everything under this folder is loaded; a string: the next page. */
  cursor: string | null;
  /** The last path listed so far; listings are sorted by path, so everything before it is loaded. */
  last?: string | undefined;
}

interface TreeArgs {
  owner: string;
  repo: string;
  ref: string;
  /** The `tags` search param (comma-separated), so the hook's identity only changes with it. */
  tags: string | undefined;
  /** The open article: its folders start expanded. */
  selected: string | undefined;
}

/**
 * The lazily loaded tree of one version (and tag filter): the root listing loads on mount, a
 * folder's listing when it is first expanded, and each listing pages on request. Mount it with a
 * `key` of version and tags so a change starts from nothing.
 */
export function useTree({ owner, repo, ref, tags: tagsParam, selected }: TreeArgs) {
  const queryClient = useQueryClient();
  const tags = useMemo(() => parseTags(tagsParam), [tagsParam]);
  const [articles, setArticles] = useState<ReadonlyMap<string, ArticleSummary>>(new Map());
  const [scopes, setScopes] = useState<Readonly<Record<string, Scope>>>({});
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(
    () => new Set(selected ? ancestorsOf(selected) : []),
  );
  const scopesRef = useRef(scopes);
  useEffect(() => {
    scopesRef.current = scopes;
  }, [scopes]);

  const load = useCallback(
    async (prefix: string) => {
      const current = scopesRef.current[prefix];
      if (current?.status === "loading") return;
      const cursor = current?.cursor;
      if (current?.status === "idle" && cursor === null) return;
      setScopes((s) => ({
        ...s,
        [prefix]: { status: "loading", cursor: cursor ?? null, last: current?.last },
      }));
      try {
        const page = await queryClient.fetchQuery(
          articlesPageQueryOptions({ owner, repo, ref, tags, prefix, cursor }),
        );
        setArticles((prev) => {
          const next = new Map(prev);
          for (const a of page.articles) next.set(a.path, a);
          return next;
        });
        const last = page.articles.at(-1)?.path ?? current?.last;
        setScopes((s) => ({ ...s, [prefix]: { status: "idle", cursor: page.next_cursor, last } }));
      } catch {
        setScopes((s) => ({
          ...s,
          [prefix]: { status: "error", cursor: cursor ?? null, last: current?.last },
        }));
      }
    },
    [queryClient, owner, repo, ref, tags],
  );

  const root = scopes[""];
  // A folder is complete when it, or any folder above it, has been listed to the end, or when the
  // root listing has already run past it (the listing is sorted, so a folder is contiguous).
  const complete = useCallback(
    (folder: string) => {
      const last = scopes[""]?.last;
      const passed =
        folder !== "" &&
        last !== undefined &&
        !last.startsWith(`${folder}/`) &&
        last > `${folder}/`;
      return (
        passed ||
        [...ancestorsOf(`${folder}/_`), ""].some(
          (f) => scopes[f]?.status === "idle" && scopes[f]?.cursor === null,
        )
      );
    },
    [scopes],
  );

  useEffect(() => {
    void load("");
  }, [load]);

  // The article's folders open when the URL moves to another folder.
  useEffect(() => {
    if (!selected) return;
    setExpanded((prev) => {
      const missing = ancestorsOf(selected).filter((f) => !prev.has(f));
      return missing.length ? new Set([...prev, ...missing]) : prev;
    });
  }, [selected]);

  // Opening a folder lists it unless a listing above already covers it all.
  const rootReady = root?.status === "idle";
  useEffect(() => {
    if (!rootReady) return;
    for (const folder of expanded) {
      if (!scopesRef.current[folder] && !complete(folder)) void load(folder);
    }
  }, [expanded, rootReady, complete, load]);

  const toggle = useCallback((folder: string, open?: boolean) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (open ?? !prev.has(folder)) next.add(folder);
      else next.delete(folder);
      return next;
    });
  }, []);

  const rows = useMemo(() => {
    const partial = new Set<string>();
    const loading = new Set<string>();
    for (const [folder, scope] of Object.entries(scopes)) {
      if (scope.status === "loading" && scope.cursor === null) loading.add(folder);
      if (scope.status === "error" || (scope.cursor !== null && !complete(folder))) {
        partial.add(folder);
      }
    }
    return buildRows(articles.values(), expanded, partial, loading);
  }, [articles, expanded, scopes, complete]);

  return {
    rows,
    articles,
    status:
      !root || (root.status === "loading" && articles.size === 0)
        ? "loading"
        : root.status === "error" && articles.size === 0
          ? "error"
          : "ready",
    scopes,
    toggle,
    load,
    retry: () => load(""),
  } as const;
}
