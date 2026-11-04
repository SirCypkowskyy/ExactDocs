import { queryOptions } from "@tanstack/react-query";
import type { components } from "./api-schema";
import { getJson, type QueryOf } from "./http";
import { BROWSE_KEY } from "./query-keys";

type TagList = components["schemas"]["TagList"];

/** One version of one library, as the tag facets need it. */
export interface TagsArgs {
  owner: string;
  repo: string;
  ref: string;
  /** The commit the ref pointed at: part of the key, so a re-import never shows old counts. */
  sha: string;
}

/** The version's tags with their article counts. Browse and search share this one query. */
export const tagsQueryOptions = ({ owner, repo, ref, sha }: TagsArgs) =>
  queryOptions({
    queryKey: [...BROWSE_KEY, owner, repo, ref, sha, "tags"] as const,
    queryFn: ({ signal }) => {
      const query: QueryOf<"/api/v1/libraries/{owner}/{repo}/tags"> = { ref };
      return getJson<TagList>(
        `/v1/libraries/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/tags`,
        { signal, query },
      );
    },
  });
