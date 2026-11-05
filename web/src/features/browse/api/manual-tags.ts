import type { QueryClient } from "@tanstack/react-query";
import type { components } from "@/shared/lib/api-schema";
import { sendJson } from "@/shared/lib/http";
import { BROWSE_KEY } from "@/shared/lib/query-keys";

type TaggedArticle = components["schemas"]["TaggedArticle"];
type ManualTagsIn = components["schemas"]["ManualTagsIn"];

const seg = encodeURIComponent;
/** The path travels as a query parameter: it holds `/`. */
const tagsPath = (owner: string, repo: string, path: string) =>
  `/v1/libraries/${seg(owner)}/${seg(repo)}/tags?path=${seg(path)}` as const;

/**
 * Set the manual tags of an article path for every version of the library, replacing the path's
 * earlier ones; no tags removes them (`DELETE`). Imported tags are never touched.
 */
export function setManualTags(
  owner: string,
  repo: string,
  path: string,
  tags: readonly string[],
): Promise<TaggedArticle | undefined> {
  if (tags.length === 0) return sendJson<undefined>("DELETE", tagsPath(owner, repo, path));
  const body: ManualTagsIn = { tags };
  return sendJson<TaggedArticle>("PUT", tagsPath(owner, repo, path), body);
}

/**
 * Manual tags hold for every version: the articles, the trees, the tag filters and the searches
 * of every version may have changed, so all of the browse queries reload.
 */
export function refreshTags(queryClient: QueryClient) {
  return queryClient.invalidateQueries({ queryKey: BROWSE_KEY });
}
