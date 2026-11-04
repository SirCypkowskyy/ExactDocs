import type { TagMatch } from "./search";

/** What the box and the results share: the selected version and the URL's search state. */
export interface SearchContext {
  owner: string;
  repo: string;
  ref: string;
  sha: string;
  /** The query from the URL, already trimmed; absent when there is nothing to search for. */
  q: string | undefined;
  /** The comma-separated `tags` search param. */
  tags: string | undefined;
  match: TagMatch;
  /** Other imported versions, for the "no results" suggestion. */
  otherRefs: readonly string[];
}
