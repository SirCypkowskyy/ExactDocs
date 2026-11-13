import { describe, expect, it } from "vitest";
import { addedNothing, addTag, keptNotice, tagGroups, tagsSetOn, withoutTag } from "./article-tags";

type Origin = "front_matter" | "path_rule" | "imported" | "manual";
const origins = (...pairs: [string, Origin[]][]) =>
  pairs.map(([tag, from]) => ({ tag, origins: from }));

const article = {
  tags: ["guide", "setup", "onboarding", "legacy"],
  tag_origins: origins(
    ["guide", ["path_rule"]],
    ["setup", ["front_matter"]],
    ["onboarding", ["manual"]],
    ["legacy", ["manual"]],
  ),
  manual_tags: [
    { tag: "onboarding", path: "guide/install.md" },
    { tag: "legacy", path: "old/install.md" },
  ],
};

describe("tagGroups", () => {
  it("sorts the tags by the origins the API gives", () => {
    expect(tagGroups(article)).toEqual({
      frontMatter: ["setup"],
      rules: ["guide"],
      imported: [],
      manual: article.manual_tags,
    });
  });

  it("lists a tag with several origins under each", () => {
    const groups = tagGroups({
      tag_origins: origins(
        ["guides", ["path_rule", "manual"]],
        ["guide", ["front_matter", "path_rule"]],
        ["install", ["front_matter"]],
      ),
      manual_tags: [{ tag: "guides", path: "a.md" }],
    });
    expect(groups).toEqual({
      frontMatter: ["guide", "install"],
      rules: ["guides", "guide"],
      imported: [],
      manual: [{ tag: "guides", path: "a.md" }],
    });
  });

  it("keeps imported tags whose origin was not recorded apart", () => {
    const groups = tagGroups({ tag_origins: origins(["a", ["imported"]]), manual_tags: [] });
    expect(groups).toEqual({ frontMatter: [], rules: [], imported: ["a"], manual: [] });
  });

  it("does not read the front matter: the API's origins are what counts", () => {
    // ß is folded to ss by the server, which a client-side copy would get wrong.
    const groups = tagGroups({
      tag_origins: origins(["strasse", ["front_matter"]]),
      manual_tags: [],
    });
    expect(groups.frontMatter).toEqual(["strasse"]);
    expect(groups.rules).toEqual([]);
  });
});

describe("editing manual tags", () => {
  it("adds what was typed, trimmed, to the path's own manual tags only: the server makes the tag", () => {
    expect(tagsSetOn(article.manual_tags, "guide/install.md")).toEqual(["onboarding"]);
    expect(addTag({ ...article, path: "guide/install.md" }, "  Getting Started ")).toEqual({
      ok: true,
      tags: ["onboarding", "Getting Started"],
    });
  });

  it("refuses a value without a tag's shape, and a 21st tag", () => {
    const empty = { path: "a.md", tags: [], manual_tags: [] };
    expect(addTag(empty, "#nope")).toEqual({ ok: false, reason: "invalid" });
    expect(addTag(empty, "   ")).toEqual({ ok: false, reason: "invalid" });
    expect(addTag(empty, "x".repeat(41))).toEqual({ ok: false, reason: "invalid" });
    const full = Array.from({ length: 20 }, (_, i) => ({ tag: `t${i}`, path: "a.md" }));
    expect(addTag({ ...empty, manual_tags: full }, "one-more")).toEqual({
      ok: false,
      reason: "too-many",
    });
  });

  it("refuses a tag the article already has: set by hand here or on an older path, or imported", () => {
    const install = { ...article, path: "guide/install.md" };
    for (const tag of ["ONBOARDING", "legacy", "guide", "Setup"]) {
      expect(addTag(install, tag)).toEqual({ ok: false, reason: "duplicate" });
    }
  });

  it("tells when the server's answer holds no new tag", () => {
    expect(addedNothing(["a"], ["a", "getting-started"])).toBe(false);
    expect(addedNothing(["getting-started"], ["getting-started"])).toBe(true);
  });

  it("removes a tag on the path it was set on, keeping that path's others", () => {
    expect(withoutTag(article.manual_tags, { tag: "legacy", path: "old/install.md" })).toEqual([]);
    const two = [...article.manual_tags, { tag: "keep", path: "guide/install.md" }];
    expect(withoutTag(two, { tag: "onboarding", path: "guide/install.md" })).toEqual(["keep"]);
  });

  it("says a tag removed by hand stays only when another origin still gives it", () => {
    const kept = { tag_origins: origins(["guide", ["path_rule"]]) };
    expect(keptNotice(kept, "guide")).toBe("guide stays on this article: its import gives it too.");
    expect(keptNotice({ tag_origins: [] }, "guide")).toBeUndefined();
    expect(keptNotice({ tag_origins: origins(["guide", ["manual"]]) }, "guide")).toBeUndefined();
    expect(keptNotice(kept, undefined)).toBeUndefined();
  });
});
