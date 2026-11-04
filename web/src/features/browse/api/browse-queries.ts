import { queryOptions } from "@tanstack/react-query";
import { getJson, type QueryOf } from "@/shared/lib/http";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import type { Article, ArticleList, LibraryAccess, LibraryDetail } from "../model/browse";

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
