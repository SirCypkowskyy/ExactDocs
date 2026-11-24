import { currentLanguage, type Language, messagesFor } from "@/shared/lib/i18n";
import { isTagShaped, MAX_TAGS, sameTag } from "@/shared/lib/tags";
import { messages } from "../messages";
import type { Article } from "./browse";

export type ManualTag = Article["manual_tags"][number];
type TagOrigin = Article["tag_origins"][number]["origins"][number];

/** Where the tags of an article come from, as the tag editor shows them (TAG-01). */
export interface TagGroups {
  /** Declared in the file's front matter. */
  frontMatter: string[];
  /** Given by the library's path rules. */
  rules: string[];
  /** Imported, from the front matter or a path rule: a version imported before that was recorded. */
  imported: string[];
  /** Set by hand, each with the path it was set on (this one, or one it was renamed from). */
  manual: ManualTag[];
}

/** The article's tags that come from `origin`, in the article's order. */
const tagsFrom = (article: Pick<Article, "tag_origins">, origin: TagOrigin): string[] =>
  article.tag_origins.filter((t) => t.origins.includes(origin)).map((t) => t.tag);

/**
 * Sort an article's tags by origin, as the API reports them (`tag_origins`). A tag with several
 * origins is listed under each: a path-rule tag also set by hand shows under both, and stays
 * under "Path rules" once it is removed by hand.
 */
export function tagGroups(article: Pick<Article, "tag_origins" | "manual_tags">): TagGroups {
  return {
    frontMatter: tagsFrom(article, "front_matter"),
    rules: tagsFrom(article, "path_rule"),
    imported: tagsFrom(article, "imported"),
    manual: [...article.manual_tags],
  };
}

/** The manual tags set on `path` itself: what a `PUT` on that path replaces. */
export const tagsSetOn = (manual: readonly ManualTag[], path: string): string[] =>
  manual.filter((m) => m.path === path).map((m) => m.tag);

/** Why a typed tag cannot be added, or the tags to send for `path` once it is. */
export type AddResult =
  | { ok: true; tags: string[] }
  | { ok: false; reason: "invalid" | "duplicate" | "too-many" };

/**
 * Add what the user typed to the manual tags of the article's path. It is sent as typed: the
 * server makes the tag (case folding, spaces as `-`) and its answer is what the page shows.
 * Refused here: a value without a tag's shape, a tag the article already has from anywhere
 * (imported, or set by hand on this path or on one it was renamed from) in any letter case, and
 * a tag past the path's limit.
 */
export function addTag(
  article: Pick<Article, "path" | "tags" | "manual_tags">,
  raw: string,
): AddResult {
  const typed = raw.trim();
  if (!isTagShaped(typed)) return { ok: false, reason: "invalid" };
  const known = [...article.tags, ...article.manual_tags.map((m) => m.tag)];
  if (known.some((t) => sameTag(t, typed))) return { ok: false, reason: "duplicate" };
  const own = tagsSetOn(article.manual_tags, article.path);
  if (own.length >= MAX_TAGS) return { ok: false, reason: "too-many" };
  return { ok: true, tags: [...own, typed] };
}

/**
 * Whether the server's answer to adding one tag to a path that had `before` holds no new tag:
 * once the server made it a tag, what was typed is one the path already had. Looks for a new
 * member rather than comparing lengths, so a tag removed meanwhile (another tab) does not hide
 * a real addition.
 */
export function addedNothing(before: readonly string[], after: readonly string[]): boolean {
  const had = new Set(before);
  return after.every((t) => had.has(t));
}

/** The manual tags `removed.path` keeps without `removed.tag`; empty means remove them all. */
export const withoutTag = (manual: readonly ManualTag[], removed: ManualTag): string[] =>
  tagsSetOn(manual, removed.path).filter((t) => t !== removed.tag);

/** What to say after `removed` was taken off by hand but the article still has it: imported too. */
export function keptNotice(
  article: Pick<Article, "tag_origins">,
  removed: string | undefined,
  language: Language = currentLanguage(),
): string | undefined {
  if (removed === undefined) return undefined;
  const kept = article.tag_origins.find((t) => t.tag === removed);
  if (kept === undefined || kept.origins.includes("manual")) return undefined;
  return messagesFor(messages, language).tags.kept(removed);
}
