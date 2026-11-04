import { queryOptions } from "@tanstack/react-query";
import { getJson } from "@/shared/lib/http";
import type { Article, ArticleList, LibraryDetail } from "../model/browse";

/** How many articles one request lists. The API allows 200. */
const PAGE_SIZE = 100;

const seg = encodeURIComponent;

const browseKeys = {
  all: ["browse"] as const,
  library: (owner: string, repo: string) => [...browseKeys.all, owner, repo, "library"] as const,
  articles: (
    owner: string,
    repo: string,
    ref: string,
    tags: string,
    prefix: string,
    cursor: string,
  ) => [...browseKeys.all, owner, repo, ref, "articles", tags, prefix, cursor] as const,
  article: (owner: string, repo: string, ref: string, path: string) =>
    [...browseKeys.all, owner, repo, ref, "article", path] as const,
};

export const libraryQueryOptions = (owner: string, repo: string) =>
  queryOptions({
    queryKey: browseKeys.library(owner, repo),
    queryFn: ({ signal }) =>
      getJson<LibraryDetail>(`/v1/libraries/${seg(owner)}/${seg(repo)}`, { signal }),
  });

export interface ListArgs {
  owner: string;
  repo: string;
  ref: string;
  tags: readonly string[];
  /** A folder (`docs/guide`), or empty for the whole version. */
  prefix: string;
  cursor?: string | null | undefined;
}

/** One page of the version's articles under a folder; paging is by the API's opaque cursor. */
export const articlesPageQueryOptions = ({ owner, repo, ref, tags, prefix, cursor }: ListArgs) =>
  queryOptions({
    queryKey: browseKeys.articles(owner, repo, ref, tags.join(","), prefix, cursor ?? ""),
    // No abort signal: the tree fetches pages imperatively (`fetchQuery`) while the tag filter
    // observes the same first page, and an observer leaving must not cancel the tree's request.
    queryFn: () =>
      getJson<ArticleList>(`/v1/libraries/${seg(owner)}/${seg(repo)}/articles`, {
        query: {
          ref,
          path_prefix: prefix,
          tags,
          limit: PAGE_SIZE,
          cursor: cursor ?? undefined,
        },
      }),
  });

/** Refs and paths travel as query parameters: a ref may contain `/`. */
export const articleQueryOptions = (owner: string, repo: string, ref: string, path: string) =>
  queryOptions({
    queryKey: browseKeys.article(owner, repo, ref, path),
    queryFn: ({ signal }) =>
      getJson<Article>(`/v1/libraries/${seg(owner)}/${seg(repo)}/article`, {
        signal,
        query: { ref, path },
      }),
  });
