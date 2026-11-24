import { queryOptions } from "@tanstack/react-query";
import { getJson, HttpError, type QueryOf } from "@/shared/lib/http";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import type { ServerSource } from "@/shared/ui/data-table/server-pages";
import type { ArticleFilters } from "../model/articles-view";
import {
  type Article,
  type ArticleList,
  type ArticleSummary,
  type LibraryAccess,
  type LibraryDetail,
  pathInVersion,
  type RenameAnswer,
  type RenameDirection,
  type Version,
} from "../model/browse";

/** How many articles one request lists. The API allows 200. */
const PAGE_SIZE = 100;

const seg = encodeURIComponent;
const lib = (owner: string, repo: string) => `/v1/libraries/${seg(owner)}/${seg(repo)}` as const;

/** Keys carry the commit, so a re-imported branch (same ref, new commit) never shows old content. */
const browseKeys = {
  library: (owner: string, repo: string) => [...BROWSE_KEY, owner, repo, "library"] as const,
  articles: (
    owner: string,
    repo: string,
    ref: string,
    sha: string,
    tags: string,
    prefix: string,
    cursor: string,
  ) => [...BROWSE_KEY, owner, repo, ref, sha, "articles", tags, prefix, cursor] as const,
  article: (owner: string, repo: string, ref: string, sha: string, path: string) =>
    [...BROWSE_KEY, owner, repo, ref, sha, "article", path] as const,
};

export const libraryQueryOptions = (owner: string, repo: string) =>
  queryOptions({
    queryKey: browseKeys.library(owner, repo),
    queryFn: ({ signal }) => getJson<LibraryDetail>(lib(owner, repo), { signal }),
  });

/** One version of one library: its ref and the commit that ref pointed at when imported. */
export interface VersionArgs {
  owner: string;
  repo: string;
  ref: string;
  sha: string;
}

export interface ListArgs extends VersionArgs {
  tags: readonly string[];
  /** A folder (`docs/guide`), or empty for the whole version. */
  prefix: string;
  cursor?: string | undefined;
}

/** One page of the version's articles under a folder; paging is by the API's opaque cursor. */
export const articlesPageQueryOptions = ({
  owner,
  repo,
  ref,
  sha,
  tags,
  prefix,
  cursor,
}: ListArgs) =>
  queryOptions({
    queryKey: browseKeys.articles(owner, repo, ref, sha, tags.join(","), prefix, cursor ?? ""),
    queryFn: ({ signal }) => {
      const query: QueryOf<"/api/v1/libraries/{owner}/{repo}/articles"> = {
        ref,
        path_prefix: prefix,
        tags,
        limit: PAGE_SIZE,
        cursor: cursor ?? null,
      };
      return getJson<ArticleList>(`${lib(owner, repo)}/articles`, { signal, query });
    },
  });

/**
 * The articles table's rows (DataTable v2, server mode): numbered pages by offset (any page in
 * one request), sorted and filtered (path or title, tags, folder) by the server. The key carries the commit and
 * the view, never the page or the size.
 */
export function articlesSource(
  { owner, repo, ref, sha }: VersionArgs,
  filters: ArticleFilters,
): ServerSource<ArticleSummary> {
  return {
    key: [...BROWSE_KEY, owner, repo, ref, sha, "article-table", filters] as const,
    paging: "offset",
    fetchPage: ({ limit, cursor, offset, signal }) => {
      const query: QueryOf<"/api/v1/libraries/{owner}/{repo}/articles"> = {
        ref,
        tags: filters.tags,
        q: filters.q ?? null,
        sort: filters.sort ?? null,
        limit,
        // A page by offset, or after a cursor past the offset's bound; never both.
        ...(offset !== undefined ? { offset } : { cursor }),
        // Left out for the whole version (an empty prefix is the tree's root listing).
        ...(filters.prefix && { path_prefix: filters.prefix }),
      };
      return getJson<ArticleList>(`${lib(owner, repo)}/articles`, { signal, query }).then(
        (list) => ({ rows: list.articles, total: list.total, nextCursor: list.next_cursor }),
      );
    },
  };
}

/** Refs and paths travel as query parameters: a ref may contain `/`. */
export const articleQueryOptions = ({ owner, repo, ref, sha }: VersionArgs, path: string) =>
  queryOptions({
    queryKey: browseKeys.article(owner, repo, ref, sha, path),
    queryFn: ({ signal }) => {
      const query: QueryOf<"/api/v1/libraries/{owner}/{repo}/article"> = { ref, path };
      return getJson<Article>(`${lib(owner, repo)}/article`, { signal, query });
    },
  });

/** Whether the library is private (it has a stored credential): its images are never linked to the host. */
export const accessQueryOptions = (owner: string, repo: string) =>
  queryOptions({
    queryKey: [...BROWSE_KEY, owner, repo, "access"] as const,
    queryFn: ({ signal }) => getJson<LibraryAccess>(`${lib(owner, repo)}/access`, { signal }),
    staleTime: 60_000,
  });

/**
 * How long one rename lookup may take. The answer only refines the version switch (without it the
 * path is kept), so a slow or failing server is not waited for, and the lookup is not retried.
 */
export const RENAME_LOOKUP_TIMEOUT_MS = 1500;

/**
 * Where `path` moved across the renames of the version, one hop (`forward`: from the version
 * imported before it; `back`: to it). `null`: not moved.
 */
const renamedPathQueryOptions = (
  { owner, repo, ref, sha }: VersionArgs,
  path: string,
  direction: RenameDirection,
) =>
  queryOptions({
    queryKey: [...BROWSE_KEY, owner, repo, ref, sha, "renamed", direction, path] as const,
    queryFn: async ({ signal }) => {
      const query: QueryOf<"/api/v1/libraries/{owner}/{repo}/renamed-path"> = {
        ref,
        path,
        direction,
      };
      const answer = await getJson<RenameAnswer>(`${lib(owner, repo)}/renamed-path`, {
        signal: AbortSignal.any([signal, AbortSignal.timeout(RENAME_LOOKUP_TIMEOUT_MS)]),
        query,
      });
      return answer.renamed;
    },
    retry: false,
    staleTime: 60_000,
  });

/**
 * Where `path`, which this version does not have, went when the version was imported: the new
 * path git saw it renamed to, or `null`. One hop: the version's own map (a link only knows the
 * version, not the one it came from); a failed lookup is no answer (the "not in this version"
 * page stays). Same short timeout, no retry.
 */
export const renamedInVersionQueryOptions = (version: VersionArgs, path: string) =>
  queryOptions({
    ...renamedPathQueryOptions(version, path, "forward"),
    select: (renamed) => (renamed && renamed.new_path !== path ? renamed.new_path : null),
  });

/** Where the open article is in another version (see `pathInVersionQueryOptions`). */
interface PathInVersion {
  path: string;
  /**
   * False when a lookup failed in a way that may pass (a timeout, the network, a server error):
   * the path is kept for now, and the answer is asked again the next time the list opens.
   */
  sure: boolean;
}

/** A failure that asking again will not change: the version has no rename map, or no access. */
const lasting = (error: unknown) => error instanceof HttpError && error.status < 500;

/**
 * The path of the article at `path` of `from` in `to`, following the renames between the two (see
 * `pathInVersion`). It never fails: without an answer the path is kept. The server walks every
 * version in between, so resolving N versions asks it N times, once per target. An answer kept
 * after a passing failure is stale at once, so a short stall does not stick for the full minute.
 */
export const pathInVersionQueryOptions = (
  owner: string,
  repo: string,
  from: Version,
  to: Version,
  path: string,
) =>
  queryOptions({
    queryKey: [
      ...BROWSE_KEY,
      owner,
      repo,
      "path-in",
      from.ref,
      from.commit_sha,
      to.ref,
      to.commit_sha,
      path,
    ] as const,
    queryFn: async ({ signal }): Promise<PathInVersion> => {
      let sure = true;
      const moved = await pathInVersion(
        async (start, target, at) => {
          const query: QueryOf<"/api/v1/libraries/{owner}/{repo}/renamed-path"> = {
            ref: target,
            from: start,
            path: at,
          };
          try {
            const answer = await getJson<RenameAnswer>(`${lib(owner, repo)}/renamed-path`, {
              signal: AbortSignal.any([signal, AbortSignal.timeout(RENAME_LOOKUP_TIMEOUT_MS)]),
              query,
            });
            return answer.renamed;
          } catch (error) {
            if (!lasting(error)) sure = false;
            throw error;
          }
        },
        from.ref,
        to.ref,
        path,
      );
      return { path: moved, sure };
    },
    retry: false,
    staleTime: (query) => (query.state.data?.sure === false ? 0 : 60_000),
  });
