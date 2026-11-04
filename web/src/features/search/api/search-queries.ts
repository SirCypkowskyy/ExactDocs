import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { getJson, type QueryOf } from "@/shared/lib/http";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import { normalizeQuery } from "@/shared/lib/search-query";
import { parseTags } from "@/shared/lib/tags";
import type { SearchResults, TagMatch } from "../model/search";

/** One screen of hits; the API allows 50. */
const SEARCH_LIMIT = 20;

export interface SearchArgs {
  owner: string;
  repo: string;
  ref: string;
  /** The commit the version points at: part of the key, so a re-import never shows old hits. */
  sha: string;
  q: string;
  /** The `tags` URL param (comma-separated). */
  tags: string | undefined;
  match: TagMatch;
}

/** Everything sent is capped here, whatever the URL held: a query over 1000 characters is a 422. */
export const searchQueryOptions = ({ owner, repo, ref, sha, q, tags, match }: SearchArgs) => {
  const text = normalizeQuery(q) ?? "";
  const tagList = parseTags(tags);
  return queryOptions({
    queryKey: [
      ...BROWSE_KEY,
      owner,
      repo,
      ref,
      sha,
      "search",
      text,
      tagList.join(","),
      match,
    ] as const,
    queryFn: ({ signal }) => {
      const query: QueryOf<"/api/v1/libraries/{owner}/{repo}/search"> = {
        q: text,
        ref,
        tags: tagList,
        tags_match: match,
        limit: SEARCH_LIMIT,
      };
      return getJson<SearchResults>(
        `/v1/libraries/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/search`,
        { signal, query },
      );
    },
    // Typing replaces the list in place instead of flashing a skeleton between keystrokes.
    placeholderData: keepPreviousData,
  });
};
