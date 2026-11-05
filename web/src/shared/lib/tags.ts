/** Most tags the API accepts in one filter, and on one article path by hand (docs/rest-api.md). */
export const MAX_TAGS = 20;
/** Longest value the API reads in a tag filter; anything longer matches nothing. */
const MAX_TAG_INPUT = 100;
/** Longest tag the API stores (the kernel's `MAX_TAG_LENGTH`). */
export const MAX_TAG_LENGTH = 40;

const TAG = /^[\p{L}\p{N}][\p{L}\p{N}\p{M}._+-]*$/u;

/**
 * A tag in its one form, as the API stores it, or `undefined` when `raw` cannot be a tag:
 * NFKC, lower-case, inner whitespace as `-`; it starts with a letter or digit and goes on with
 * letters, digits, combining marks and `._+-`; 40 characters at most. The server folds case a
 * little further (`ß` is `ss`), so its answer is the one to show.
 */
export function normalizeTag(raw: string): string | undefined {
  const folded = raw.normalize("NFKC").toLowerCase().normalize("NFKC");
  const tag = folded.trim().split(/\s+/u).join("-");
  return tag !== "" && tag.length <= MAX_TAG_LENGTH && TAG.test(tag) ? tag : undefined;
}

/** The `tags` URL param as a list. Over-long tags and anything past 20 are dropped, as the API would refuse them. */
export const parseTags = (tags: string | undefined): string[] =>
  (tags ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t !== "" && t.length <= MAX_TAG_INPUT)
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
