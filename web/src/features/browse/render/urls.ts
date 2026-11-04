import { repoWebUrl } from "../model/browse";

/** Resolve `href` against the article's folder; a repository path, or undefined when it leaves the repository. */
export function repoPath(articlePath: string, href: string): string | undefined {
  const [raw = ""] = href.split(/[?#]/, 1);
  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    return undefined;
  }
  if (!decoded) return undefined;
  const parts = decoded.startsWith("/") ? [] : articlePath.split("/").slice(0, -1);
  for (const part of decoded.split("/")) {
    if (part === "..") {
      if (parts.length === 0) return undefined;
      parts.pop();
    } else if (part !== "." && part !== "") {
      parts.push(part);
    }
  }
  return parts.length ? parts.join("/") : undefined;
}

const encode = (path: string) => path.split("/").map(encodeURIComponent).join("/");

// Where the host serves a file's bytes, and its page, at a commit.
const RAW = {
  github: "raw",
  gitlab: "-/raw",
  bitbucket: "raw",
  gitea: "raw/commit",
} as const;
const BLOB = {
  github: "blob",
  gitlab: "-/blob",
  bitbucket: "src",
  gitea: "src/commit",
} as const;

type Kind = keyof typeof RAW;
const known = (host: string): host is Kind => Object.hasOwn(RAW, host);

/** The file's bytes at the commit, for an `<img>`; undefined for a host that has no such URL. */
export function rawUrl(
  host: string,
  sourceUrl: string,
  sha: string,
  path: string,
): string | undefined {
  const base = repoWebUrl(sourceUrl);
  if (!base || !known(host) || !/^[0-9a-f]{7,64}$/i.test(sha)) return undefined;
  if (host === "github" && base.startsWith("https://github.com/")) {
    return `https://raw.githubusercontent.com/${base.slice("https://github.com/".length)}/${sha}/${encode(path)}`;
  }
  return `${base}/${RAW[host]}/${sha}/${encode(path)}`;
}

/** The file's page on the host at the commit. */
export function blobUrl(
  host: string,
  sourceUrl: string,
  sha: string,
  path: string,
): string | undefined {
  const base = repoWebUrl(sourceUrl);
  if (!base || !known(host) || !/^[0-9a-f]{7,64}$/i.test(sha)) return undefined;
  return `${base}/${BLOB[host]}/${sha}/${encode(path)}`;
}

export type LinkTarget =
  | { kind: "hash"; href: string }
  | { kind: "external"; href: string }
  | { kind: "doc"; path: string; hash: string }
  | { kind: "file"; path: string }
  | { kind: "none" };

/** What a Markdown link points at. Only http(s) and mailto leave the app; every other scheme is text. */
export function classifyLink(articlePath: string, href: string): LinkTarget {
  const target = href.trim();
  if (target.startsWith("#")) return { kind: "hash", href: target };
  if (/^(https?:\/\/|mailto:)/i.test(target)) return { kind: "external", href: target };
  if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith("//")) return { kind: "none" };
  const path = repoPath(articlePath, target);
  if (!path) return { kind: "none" };
  if (/\.mdx?$/i.test(path)) {
    const hash = target.includes("#") ? target.slice(target.indexOf("#")) : "";
    return { kind: "doc", path, hash };
  }
  return { kind: "file", path };
}
