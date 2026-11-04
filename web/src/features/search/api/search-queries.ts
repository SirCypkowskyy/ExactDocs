import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { getJson, type QueryOf } from "@/shared/lib/http";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import { type SearchResults, sendableTags, type TagCount, type TagMatch } from "../model/search";

/** One screen of hits; the API allows 50. */
const SEARCH_LIMIT = 20;

export interface SearchArgs {
  owner: string;
  repo: string;
  ref: string;
  /** The commit the version points at: part of the key, so a re-import never shows old hits. */
  sha: string;
  q: string;
  tags: readonly string[];
  match: TagMatch;
}

const base = (owner: string, repo: string) =>
  `/v1/libraries/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}` as const;

export const searchQueryOptions = ({ owner, repo, ref, sha, q, tags, match }: SearchArgs) =>
  queryOptions({
    queryKey: [...BROWSE_KEY, owner, repo, ref, sha, "search", q, tags.join(","), match] as const,
    queryFn: ({ signal }) => {
      const query: QueryOf<"/api/v1/libraries/{owner}/{repo}/search"> = {
        q,
        ref,
        tags: sendableTags(tags),
        tags_match: match,
        limit: SEARCH_LIMIT,
      };
      return getJson<SearchResults>(`${base(owner, repo)}/search`, { signal, query });
    },
    // Typing replaces the list in place instead of flashing a skeleton between keystrokes.
    placeholderData: keepPreviousData,
  });

export const searchTagsQueryOptions = (a: Pick<SearchArgs, "owner" | "repo" | "ref" | "sha">) =>
  queryOptions({
    queryKey: [...BROWSE_KEY, a.owner, a.repo, a.ref, a.sha, "tags"] as const,
    queryFn: ({ signal }) => {
      const query: QueryOf<"/api/v1/libraries/{owner}/{repo}/tags"> = { ref: a.ref };
      return getJson<TagCount>(`${base(a.owner, a.repo)}/tags`, { signal, query });
    },
  });
