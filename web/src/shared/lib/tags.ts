/** Longest tag and most tags the API accepts in one filter (docs/rest-api.md). */
const MAX_TAGS = 20;
const MAX_TAG_LENGTH = 100;

/** The `tags` URL param as a list. Over-long tags and anything past 20 are dropped, as the API would refuse them. */
export const parseTags = (tags: string | undefined): string[] =>
  (tags ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t !== "" && t.length <= MAX_TAG_LENGTH)
    .slice(0, MAX_TAGS);

export const sameTag = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

/** Add or remove one tag; the API ignores case, so `API` and `api` are the same tag. */
export function toggleTag(tags: readonly string[], tag: string): string | undefined {
  const next = tags.some((t) => sameTag(t, tag))
    ? tags.filter((t) => !sameTag(t, tag))
    : [...tags, tag];
  return next.length ? next.join(",") : undefined;
}

/** The chips to show: every selected tag first (so an active filter can always be undone), then the rest. */
export function visibleTags(
  selected: readonly string[],
  facets: readonly string[],
  limit = 14,
): string[] {
  const rest = facets.filter((f) => !selected.some((s) => sameTag(s, f)));
  return [...selected, ...rest].slice(0, Math.max(limit, selected.length));
}
