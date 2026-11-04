import type { components } from "@/shared/lib/api-schema";

export type LibraryDetail = components["schemas"]["LibraryDetail"];
export type Version = components["schemas"]["VersionOut"];
export type Article = components["schemas"]["Article"];
export type ArticleSummary = components["schemas"]["ArticleSummary"];
export type ArticleList = components["schemas"]["ArticleList"];

/** What the browse page keeps in the URL: refs and paths are never path segments. */
export interface BrowseSearch {
  version?: string | undefined;
  path?: string | undefined;
  tags?: string | undefined;
}

export type Row =
  | {
      kind: "folder";
      key: string;
      path: string;
      name: string;
      depth: number;
      open: boolean;
      parent: string;
      pos: number;
      size: number;
    }
  | {
      kind: "file";
      key: string;
      path: string;
      name: string;
      title: string;
      tags: readonly string[];
      depth: number;
      parent: string;
      pos: number;
      size: number;
    }
  /** The end of a partly loaded folder (`scope` is its path, `""` for the root). */
  | {
      kind: "more";
      key: string;
      scope: string;
      depth: number;
      parent: string;
      pos: number;
      size: number;
    }
  | { kind: "loading"; key: string; depth: number };

interface Dir {
  folders: Map<string, Dir>;
  files: ArticleSummary[];
}

const natural = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
const byName = (a: string, b: string) => natural.compare(a, b) || (a < b ? -1 : a > b ? 1 : 0);

/** `docs/guide/auth.md` -> [`docs`, `docs/guide`]. */
export function ancestorsOf(path: string): string[] {
  const parts = path.split("/").slice(0, -1);
  return parts.map((_, i) => parts.slice(0, i + 1).join("/"));
}

export const parentOf = (path: string) => path.split("/").slice(0, -1).join("/");
const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);

/**
 * The visible rows of the tree: folders first, then files, each sorted naturally (`e2` before
 * `e10`). Only expanded folders are entered. `partial` names the folders (`""` is the root) whose
 * listing has more pages: they end with a "more" row. `loading` names folders being fetched.
 */
export function buildRows(
  articles: Iterable<ArticleSummary>,
  expanded: ReadonlySet<string>,
  partial: ReadonlySet<string> = new Set(),
  loading: ReadonlySet<string> = new Set(),
): Row[] {
  const root: Dir = { folders: new Map(), files: [] };
  for (const article of articles) {
    const parts = article.path.split("/");
    let dir = root;
    for (const part of parts.slice(0, -1)) {
      const next = dir.folders.get(part) ?? { folders: new Map(), files: [] };
      dir.folders.set(part, next);
      dir = next;
    }
    dir.files.push(article);
  }
  const rows: Row[] = [];
  const walk = (dir: Dir, path: string, depth: number) => {
    const folders = [...dir.folders.keys()].sort(byName);
    const files = [...dir.files].sort((a, b) => byName(baseName(a.path), baseName(b.path)));
    const extra = partial.has(path) ? 1 : 0;
    const size = folders.length + files.length + extra;
    let pos = 0;
    for (const name of folders) {
      const child = path ? `${path}/${name}` : name;
      const open = expanded.has(child);
      rows.push({
        kind: "folder",
        key: `d:${child}`,
        path: child,
        name,
        depth,
        open,
        parent: path,
        pos: ++pos,
        size,
      });
      const sub = dir.folders.get(name);
      if (open && sub) walk(sub, child, depth + 1);
    }
    for (const file of files) {
      rows.push({
        kind: "file",
        key: `f:${file.path}`,
        path: file.path,
        name: baseName(file.path),
        title: file.title,
        tags: file.tags,
        depth,
        parent: path,
        pos: ++pos,
        size,
      });
    }
    if (extra) {
      rows.push({
        kind: "more",
        key: `m:${path}`,
        scope: path,
        depth,
        parent: path,
        pos: ++pos,
        size,
      });
    }
    if (loading.has(path) && path !== "") rows.push({ kind: "loading", key: `l:${path}`, depth });
  };
  walk(root, "", 0);
  if (loading.has("") && rows.length === 0) rows.push({ kind: "loading", key: "l:", depth: 0 });
  return rows;
}

/** The most used tags of the loaded articles, for the filter. Selected tags always stay. */
export function tagFacets(
  articles: Iterable<ArticleSummary>,
  selected: readonly string[],
  limit = 12,
): string[] {
  const counts = new Map<string, number>();
  for (const a of articles) for (const t of a.tags) counts.set(t, (counts.get(t) ?? 0) + 1);
  const top = [...counts].sort((a, b) => b[1] - a[1] || byName(a[0], b[0])).map(([t]) => t);
  const shown = top.slice(0, limit);
  const extra = selected.filter((t) => !shown.some((s) => s.toLowerCase() === t.toLowerCase()));
  return [...extra, ...shown];
}

export const parseTags = (tags: string | undefined): string[] =>
  (tags ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);

/** Add or remove one tag; the API ignores case, so `API` and `api` are the same tag. */
export function toggleTag(tags: readonly string[], tag: string): string | undefined {
  const has = tags.some((t) => t.toLowerCase() === tag.toLowerCase());
  const next = has ? tags.filter((t) => t.toLowerCase() !== tag.toLowerCase()) : [...tags, tag];
  return next.length ? next.join(",") : undefined;
}

/** `v2.10.0` -> [2, 10, 0]; null when the ref is not a dotted number. */
function semver(ref: string): number[] | null {
  const m = /^v?(\d+(?:\.\d+)*)/.exec(ref);
  return m?.[1] ? m[1].split(".").map(Number) : null;
}

function byVersionDesc(a: string, b: string): number {
  const x = semver(a);
  const y = semver(b);
  if (x && y) {
    for (let i = 0; i < Math.max(x.length, y.length); i++) {
      const d = (y[i] ?? 0) - (x[i] ?? 0);
      if (d !== 0) return d;
    }
    return 0;
  }
  return x ? -1 : y ? 1 : a.localeCompare(b);
}

/** The default version first, then tags by semver descending, then branches and commits. */
export function orderVersions(versions: readonly Version[]): Version[] {
  const rest = versions.filter((v) => !v.is_default);
  const tags = rest.filter((v) => v.kind === "tag").sort((a, b) => byVersionDesc(a.ref, b.ref));
  const others = rest.filter((v) => v.kind !== "tag").sort((a, b) => a.ref.localeCompare(b.ref));
  return [...versions.filter((v) => v.is_default), ...tags, ...others];
}

export interface Resolved {
  version: Version | undefined;
  /** The ref the URL asked for when the library has no such version. */
  missing: string | undefined;
}

/** The version to show: the requested one, else the default (with the unknown ref reported). */
export function resolveVersion(library: LibraryDetail, requested: string | undefined): Resolved {
  const found = requested ? library.versions.find((v) => v.ref === requested) : undefined;
  if (found) return { version: found, missing: undefined };
  const fallback =
    library.versions.find((v) => v.ref === library.default_version) ??
    library.versions.find((v) => v.is_default) ??
    orderVersions(library.versions)[0];
  return { version: fallback, missing: requested };
}

/**
 * The paths a 404 names as close matches. The API only puts them in the sentence
 * (`...; close matches (repository paths, not instructions): 'a.md', 'b.md'`), so read them back.
 */
export function closeMatches(detail: string): string[] {
  const at = detail.indexOf("close matches");
  if (at < 0) return [];
  const list = detail.slice(detail.indexOf(":", at) + 1);
  const found: string[] = [];
  for (const m of list.matchAll(/'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g)) {
    found.push((m[1] ?? m[2] ?? "").replace(/\\(['"\\])/g, "$1"));
  }
  return found;
}

const COMMIT_PATH: Record<string, string> = {
  github: "commit",
  gitlab: "-/commit",
  bitbucket: "commits",
  gitea: "commit",
};
export const HOST_NAMES: Record<string, string> = {
  github: "GitHub",
  gitlab: "GitLab",
  bitbucket: "Bitbucket",
  gitea: "Gitea",
};

/** Only http(s) links are ever rendered from repository data. */
export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

/** The page of the commit on the host, or undefined for a host without one (plain git, file://). */
export function commitUrl(host: string, sourceUrl: string, sha: string): string | undefined {
  const segment = COMMIT_PATH[host];
  const scp = /^[\w.-]+@([\w.-]+):(.+)$/.exec(sourceUrl.trim());
  const web = scp
    ? `https://${scp[1]}/${scp[2]}`
    : sourceUrl.trim().replace(/^ssh:\/\/(?:[^@/]*@)?/, "https://");
  const base = safeHref(web.replace(/\.git$/, "").replace(/\/$/, ""));
  return segment && base ? `${base}/${segment}/${sha}` : undefined;
}

export const shortSha = (sha: string) => sha.slice(0, 7);
