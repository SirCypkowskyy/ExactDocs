/** Most tags the API accepts in one filter, and on one article path by hand (docs/rest-api.md). */
export const MAX_TAGS = 20;
/** Longest value the API reads in a tag filter; anything longer matches nothing. */
const MAX_TAG_INPUT = 100;
/** Longest tag the API stores (the kernel's `MAX_TAG_LENGTH`). */
export const MAX_TAG_LENGTH = 40;

const TAG_SHAPE = /^[\p{L}\p{N}][\p{L}\p{N}\p{M}._+-]*$/u;
/**
 * Whitespace as Python's `str.split()` sees it (what the server splits on). JavaScript's `\s`
 * differs: it misses U+001C-U+001F and U+0085, and counts U+FEFF, which Python does not.
 */
function isPyWhitespace(c: string): boolean {
  const code = c.codePointAt(0) ?? 0;
  if ((code >= 0x1c && code <= 0x1f) || code === 0x85) return true;
  return code !== 0xfeff && /^\s$/u.test(c);
}

/** `s` split on whitespace and rejoined with `-`, as the server's `"-".join(s.split())`. */
function joinWords(s: string): string {
  const words: string[] = [];
  let word = "";
  for (const c of s) {
    if (!isPyWhitespace(c)) word += c;
    else if (word !== "") {
      words.push(word);
      word = "";
    }
  }
  if (word !== "") words.push(word);
  return words.join("-");
}

/**
 * Whether `raw` has the shape of a tag, for feedback while a form is filled in: after NFKC and
 * with inner whitespace (as Python's `str.split()` sees it) as `-`, it starts with a letter or
 * digit and goes on with letters, digits, combining marks and `._+-`, 40 characters at most.
 * Only a check: the server makes the tag (case folding included) and its answer is the one to
 * show; a value this lets through can still be refused there.
 */
export function isTagShaped(raw: string): boolean {
  const tag = joinWords(raw.normalize("NFKC"));
  return tag !== "" && tag.length <= MAX_TAG_LENGTH && TAG_SHAPE.test(tag);
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
