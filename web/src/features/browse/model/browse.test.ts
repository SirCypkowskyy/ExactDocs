import { describe, expect, it } from "vitest";
import {
  type ArticleSummary,
  ancestorsOf,
  buildRows,
  commitUrl,
  type LibraryDetail,
  orderVersions,
  pathInVersion,
  pinChoices,
  type RenameLookup,
  repoWebUrl,
  resolveVersion,
  safeHref,
  showFileName,
  type Version,
} from "./browse";
import { parseSearch } from "./search";

const a = (path: string, tags: string[] = [], title = path): ArticleSummary => ({
  path,
  title,
  tags,
  size: 1,
});
const v = (ref: string, kind: Version["kind"] = "tag", is_default = false): Version => ({
  ref,
  kind,
  commit_sha: "a".repeat(40),
  imported_at: "2026-11-01T10:00:00Z",
  is_default,
  origin: "manual",
});
const lib = (versions: Version[], default_version: string | null): LibraryDetail =>
  ({ id: "/a/b", versions, default_version }) as unknown as LibraryDetail;

describe("buildRows", () => {
  const articles = [
    a("README.md"),
    a("docs/guide/install.md"),
    a("docs/guide/auth.md"),
    a("docs/api/e10.md"),
    a("docs/api/e2.md"),
  ];

  it("mirrors the repository: folders first, natural order, closed folders hidden", () => {
    const rows = buildRows(articles, new Set(["docs", "docs/api"]));
    expect(
      rows.map((r) => `${r.kind === "folder" ? "d" : "f"}:${"path" in r ? r.path : ""}`),
    ).toEqual([
      "d:docs",
      "d:docs/api",
      "f:docs/api/e2.md",
      "f:docs/api/e10.md",
      "d:docs/guide",
      "f:README.md",
    ]);
  });

  it("numbers rows for assistive technology", () => {
    const rows = buildRows(articles, new Set(["docs"]));
    const guide = rows.find((r) => r.kind === "folder" && r.path === "docs/guide");
    expect(guide).toMatchObject({ depth: 1, pos: 2, size: 2, parent: "docs" });
  });

  it("ends a partly loaded folder with a more row, and the root too", () => {
    const rows = buildRows(articles, new Set(["docs"]), new Set(["docs", ""]));
    expect(rows.filter((r) => r.kind === "more").map((r) => r.kind === "more" && r.scope)).toEqual([
      "docs",
      "",
    ]);
  });

  it("shows a loading row under a folder being fetched", () => {
    const rows = buildRows([], new Set(["docs"]), new Set(), new Set([""]));
    expect(rows).toEqual([{ kind: "loading", key: "l:", depth: 0 }]);
  });

  it("lists the folders of a path", () => {
    expect(ancestorsOf("docs/guide/auth.md")).toEqual(["docs", "docs/guide"]);
    expect(ancestorsOf("README.md")).toEqual([]);
  });
});

describe("versions", () => {
  const versions = [
    v("main", "branch"),
    v("v2.9.0"),
    v("v2.10.0"),
    v("v3.0.0", "tag", true),
    v("abc1234", "commit"),
  ];

  it("orders the default first, then tags by semver, then the rest", () => {
    expect(orderVersions(versions).map((x) => x.ref)).toEqual([
      "v3.0.0",
      "v2.10.0",
      "v2.9.0",
      "abc1234",
      "main",
    ]);
  });

  it("keeps the requested version, else falls back to the default and says so", () => {
    const library = lib(versions, "v3.0.0");
    expect(resolveVersion(library, "v2.9.0")).toMatchObject({
      version: { ref: "v2.9.0" },
      missing: undefined,
    });
    expect(resolveVersion(library, undefined).version?.ref).toBe("v3.0.0");
    expect(resolveVersion(library, "v9")).toMatchObject({
      version: { ref: "v3.0.0" },
      missing: "v9",
    });
    expect(resolveVersion(lib([], null), "v1")).toEqual({ version: undefined, missing: "v1" });
  });
});

describe("links", () => {
  const sha = "0123456789abcdef";
  it("builds the repository page from whatever URL the library was added with", () => {
    expect(repoWebUrl("https://github.com/acme/p.git")).toBe("https://github.com/acme/p");
    expect(repoWebUrl("git@gitlab.com:acme/p.git")).toBe("https://gitlab.com/acme/p");
    expect(repoWebUrl("ssh://git@github.com:2222/acme/p/")).toBe("https://github.com/acme/p");
    expect(repoWebUrl("http://localhost:3000/acme/p")).toBe("http://localhost:3000/acme/p");
  });

  it("never links credentials, queries or fragments, or a URL that is no web page", () => {
    expect(repoWebUrl("https://user:token@github.com/acme/p?x=1#frag")).toBe(
      "https://github.com/acme/p",
    );
    expect(repoWebUrl("file:///srv/repo")).toBeUndefined();
    expect(repoWebUrl("git://github.com/acme/p")).toBeUndefined();
    expect(repoWebUrl("javascript:alert(1)")).toBeUndefined();
    expect(repoWebUrl("not a url")).toBeUndefined();
    expect(repoWebUrl("https://github.com/")).toBeUndefined();
  });

  it("builds the commit page per host from the origin and path only", () => {
    expect(commitUrl("github", "https://github.com/acme/p.git", sha)).toBe(
      `https://github.com/acme/p/commit/${sha}`,
    );
    expect(commitUrl("gitlab", "git@gitlab.com:acme/p.git", sha)).toBe(
      `https://gitlab.com/acme/p/-/commit/${sha}`,
    );
    expect(commitUrl("github", "ssh://git@github.com:2222/acme/p", sha)).toBe(
      `https://github.com/acme/p/commit/${sha}`,
    );
    expect(commitUrl("github", "https://u:p@github.com/acme/p?x#y", sha)).toBe(
      `https://github.com/acme/p/commit/${sha}`,
    );
    expect(commitUrl("git", "file:///tmp/repo", sha)).toBeUndefined();
  });

  it("refuses a commit that is not hex", () => {
    expect(commitUrl("github", "https://github.com/a/b", "main")).toBeUndefined();
    expect(commitUrl("github", "https://github.com/a/b", "abc1234/../x")).toBeUndefined();
    expect(commitUrl("github", "https://github.com/a/b", "abc12")).toBeUndefined();
  });

  it("never renders a script URL", () => {
    expect(safeHref("javascript:alert(1)")).toBeUndefined();
    expect(safeHref("https://example.com/x")).toBe("https://example.com/x");
    expect(safeHref(null)).toBeUndefined();
  });

  it("reads the URL's search as text", () => {
    expect(parseSearch({ version: 2, path: "a.md", tags: "", x: 1 })).toEqual({
      version: "2",
      path: "a.md",
      tags: undefined,
    });
  });
});

describe("tree rows", () => {
  it("does not claim a size for a partly loaded folder, and a more row is not an item", () => {
    const rows = buildRows([a("docs/a.md"), a("docs/b.md")], new Set(["docs"]), new Set(["docs"]));
    expect(rows.filter((r) => r.kind === "file").map((r) => r.kind === "file" && r.size)).toEqual([
      -1, -1,
    ]);
    const more = rows.find((r) => r.kind === "more");
    expect(more).toEqual({ kind: "more", key: "m:docs", scope: "docs", depth: 1 });
  });

  it("shows a failed row for a folder whose listing failed", () => {
    const rows = buildRows(
      [a("docs/a.md")],
      new Set(["docs"]),
      new Set(),
      new Set(),
      new Set(["docs"]),
    );
    expect(rows.at(-1)).toMatchObject({ kind: "failed", scope: "docs" });
  });
});

describe("showFileName", () => {
  it("hides a name that is the title in file form", () => {
    expect(showFileName("Installing", "install.md")).toBe(false);
    expect(showFileName("Authentication", "auth.md")).toBe(false);
    expect(showFileName("Endpoint 1", "endpoint-001.md")).toBe(false);
    expect(showFileName("Webhook retries", "webhook-retries.md")).toBe(false);
    expect(showFileName("Acme Payments", "README.md")).toBe(true);
    expect(showFileName("SDK quickstart", "getting-started.md")).toBe(true);
  });
});

describe("pathInVersion", () => {
  // Imported in order v1.2.0, v1.3.0, v1.4.0; v1.4.0 renamed `guide/setup.md` of v1.3.0 to
  // `guide/install.md`. The server walks the versions between `from` and `to`.
  const moves: Record<string, [string, string]> = {
    "v1.2.0>v1.4.0": ["guide/setup.md", "guide/install.md"],
    "v1.3.0>v1.4.0": ["guide/setup.md", "guide/install.md"],
    "v1.4.0>v1.2.0": ["guide/install.md", "guide/setup.md"],
    "v1.4.0>v1.3.0": ["guide/install.md", "guide/setup.md"],
  };
  const asked: string[] = [];
  const server: RenameLookup = async (from, to, path) => {
    asked.push(`${from}>${to}`);
    const [old, moved] = moves[`${from}>${to}`] ?? [];
    if (old !== path || !moved) return null;
    return {
      library: "/a/b",
      ref: to,
      from_ref: from,
      old_path: path,
      new_path: moved,
      similarity: 92,
    };
  };

  it("follows a rename to the next version and back", async () => {
    expect(await pathInVersion(server, "v1.3.0", "v1.4.0", "guide/setup.md")).toBe(
      "guide/install.md",
    );
    expect(await pathInVersion(server, "v1.4.0", "v1.3.0", "guide/install.md")).toBe(
      "guide/setup.md",
    );
  });

  it("follows a rename made in a version the switch skips, with one lookup (#201)", async () => {
    asked.length = 0;
    expect(await pathInVersion(server, "v1.2.0", "v1.4.0", "guide/setup.md")).toBe(
      "guide/install.md",
    );
    expect(asked).toEqual(["v1.2.0>v1.4.0"]);
    expect(await pathInVersion(server, "v1.4.0", "v1.2.0", "guide/install.md")).toBe(
      "guide/setup.md",
    );
  });

  it("keeps a path that did not move", async () => {
    expect(await pathInVersion(server, "v1.2.0", "v1.4.0", "guide/auth.md")).toBe("guide/auth.md");
  });

  it("ignores an answer about other versions", async () => {
    const stray: RenameLookup = async () => ({
      library: "/a/b",
      ref: "v1.4.0",
      from_ref: "v1.3.0",
      old_path: "guide/setup.md",
      new_path: "guide/install.md",
      similarity: 92,
    });
    expect(await pathInVersion(stray, "v1.2.0", "v1.4.0", "guide/setup.md")).toBe("guide/setup.md");
  });

  it("keeps the path when the server cannot be asked", async () => {
    const down: RenameLookup = () => Promise.reject(new Error("offline"));
    expect(await pathInVersion(down, "v1.3.0", "v1.4.0", "guide/setup.md")).toBe("guide/setup.md");
  });

  it("asks nothing for the same version", async () => {
    let count = 0;
    const counting: RenameLookup = async () => {
      count++;
      return null;
    };
    expect(await pathInVersion(counting, "v1.4.0", "v1.4.0", "guide/setup.md")).toBe(
      "guide/setup.md",
    );
    expect(count).toBe(0);
  });
});

describe("pinChoices", () => {
  it("offers to pin any version unless it already is the pinned default", () => {
    expect(pinChoices(v("v1.3.0"), false)).toEqual({ pin: true, unpin: false });
    expect(pinChoices(v("v1.5.0", "tag", true), false)).toEqual({ pin: true, unpin: false });
    expect(pinChoices(v("v1.3.0", "tag", true), true)).toEqual({ pin: false, unpin: true });
    expect(pinChoices(v("v1.5.0"), true)).toEqual({ pin: true, unpin: true });
  });
});
