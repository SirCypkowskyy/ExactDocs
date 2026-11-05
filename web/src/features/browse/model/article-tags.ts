import { MAX_TAGS, normalizeTag } from "@/shared/lib/tags";
import type { Article } from "./browse";

export type ManualTag = Article["manual_tags"][number];

/** Where the tags of an article come from, as the tag editor shows them (TAG-01). */
export interface TagGroups {
  /** Declared in the file's front matter. */
  frontMatter: string[];
  /** Given by the library's path rules (imported, but not from the front matter). */
  rules: string[];
  /**
   * Set by hand, each with the path it was set on (this one, or one it was renamed from).
   * `declared` marks one the front matter declares too.
   */
  manual: (ManualTag & { declared: boolean })[];
}

/** The front matter's `tags` (a list, or a comma-separated string), normalized like the importer does. */
function declaredTags(frontMatter: Article["front_matter"]): Set<string> {
  const raw = frontMatter.tags;
  const list = typeof raw === "string" ? raw.split(",") : Array.isArray(raw) ? raw : [];
  const found = new Set<string>();
  for (const item of list) {
    const tag = typeof item === "string" ? normalizeTag(item) : undefined;
    if (tag) found.add(tag);
  }
  return found;
}

/**
 * Sort an article's tags by origin. The API lists every tag in `tags` and the manual ones again in
 * `manual_tags`; the front matter tells which imported ones it declared, so the rest came from path
 * rules. A tag set by hand is listed only under "by hand", wherever else it comes from: one the
 * front matter also declares says so, but one a path rule also gives cannot be told apart (the API
 * does not say which imported tags are the rules'; #215 adds that).
 */
export function tagGroups(
  article: Pick<Article, "tags" | "manual_tags" | "front_matter">,
): TagGroups {
  const declared = declaredTags(article.front_matter);
  const manual = new Set(article.manual_tags.map((m) => m.tag));
  const imported = article.tags.filter((t) => !manual.has(t));
  return {
    frontMatter: imported.filter((t) => declared.has(t)),
    rules: imported.filter((t) => !declared.has(t)),
    manual: article.manual_tags.map((m) => ({ ...m, declared: declared.has(m.tag) })),
  };
}

/** The manual tags set on `path` itself: what a `PUT` on that path replaces. */
export const tagsSetOn = (manual: readonly ManualTag[], path: string): string[] =>
  manual.filter((m) => m.path === path).map((m) => m.tag);

/** Why a typed tag cannot be added, or the tags to send for `path` once it is. */
export type AddResult =
  | { ok: true; tags: string[]; tag: string }
  | { ok: false; reason: "invalid" | "duplicate" | "too-many" };

/**
 * Add what the user typed to the manual tags of the article's path, normalized as the API would.
 * A tag the article already has, from anywhere (imported, set by hand on this path or on one it
 * was renamed from), is refused: adding it would change nothing the reader sees.
 */
export function addTag(
  article: Pick<Article, "path" | "tags" | "manual_tags">,
  raw: string,
): AddResult {
  const tag = normalizeTag(raw);
  if (!tag) return { ok: false, reason: "invalid" };
  if (article.tags.includes(tag) || article.manual_tags.some((m) => m.tag === tag)) {
    return { ok: false, reason: "duplicate" };
  }
  const own = tagsSetOn(article.manual_tags, article.path);
  if (own.length >= MAX_TAGS) return { ok: false, reason: "too-many" };
  return { ok: true, tags: [...own, tag], tag };
}

/** The manual tags `removed.path` keeps without `removed.tag`; empty means remove them all. */
export const withoutTag = (manual: readonly ManualTag[], removed: ManualTag): string[] =>
  tagsSetOn(manual, removed.path).filter((t) => t !== removed.tag);

/** What to say after `removed` was taken off by hand but the article still has it: imported too. */
export function keptNotice(
  article: Pick<Article, "tags" | "manual_tags">,
  removed: string | undefined,
): string | undefined {
  if (removed === undefined || !article.tags.includes(removed)) return undefined;
  if (article.manual_tags.some((m) => m.tag === removed)) return undefined;
  return `${removed} stays on this article: its import gives it too.`;
}
