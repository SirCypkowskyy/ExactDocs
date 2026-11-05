import { describe, expect, it } from "vitest";
import { addTag, tagGroups, tagsSetOn, withoutTag } from "./article-tags";

const article = {
  tags: ["guide", "setup", "onboarding", "legacy"],
  front_matter: { tags: ["Setup"] },
  manual_tags: [
    { tag: "onboarding", path: "guide/install.md" },
    { tag: "legacy", path: "old/install.md" },
  ],
};

describe("tagGroups", () => {
  it("tells front-matter, rule and manual tags apart", () => {
    expect(tagGroups(article)).toEqual({
      frontMatter: ["setup"],
      rules: ["guide"],
      manual: article.manual_tags.map((m) => ({ ...m, declared: false })),
    });
  });

  it("reads front-matter tags given as one comma-separated string", () => {
    const groups = tagGroups({
      tags: ["a", "b-c", "d"],
      front_matter: { tags: "A, b  c" },
      manual_tags: [],
    });
    expect(groups.frontMatter).toEqual(["a", "b-c"]);
    expect(groups.rules).toEqual(["d"]);
  });

  it("ignores front matter whose tags are no list of text", () => {
    const groups = tagGroups({ tags: ["a"], front_matter: { tags: { a: 1 } }, manual_tags: [] });
    expect(groups).toEqual({ frontMatter: [], rules: ["a"], manual: [] });
  });

  it("lists a tag set by hand only as manual, saying when the front matter declares it too", () => {
    const groups = tagGroups({
      tags: ["setup", "guides"],
      front_matter: { tags: ["setup"] },
      manual_tags: [
        { tag: "setup", path: "a.md" },
        { tag: "guides", path: "a.md" },
      ],
    });
    expect(groups.frontMatter).toEqual([]);
    expect(groups.rules).toEqual([]);
    expect(groups.manual).toEqual([
      { tag: "setup", path: "a.md", declared: true },
      { tag: "guides", path: "a.md", declared: false },
    ]);
  });
});

describe("editing manual tags", () => {
  it("adds a tag to the path's own manual tags only, normalized", () => {
    expect(tagsSetOn(article.manual_tags, "guide/install.md")).toEqual(["onboarding"]);
    expect(addTag({ ...article, path: "guide/install.md" }, "  Getting Started ")).toEqual({
      ok: true,
      tag: "getting-started",
      tags: ["onboarding", "getting-started"],
    });
  });

  it("refuses a value that is no tag, a duplicate and a 21st tag", () => {
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
    for (const tag of ["ONBOARDING", "legacy", "guide", "setup"]) {
      expect(addTag(install, tag)).toEqual({ ok: false, reason: "duplicate" });
    }
  });

  it("removes a tag on the path it was set on, keeping that path's others", () => {
    expect(withoutTag(article.manual_tags, { tag: "legacy", path: "old/install.md" })).toEqual([]);
    const two = [...article.manual_tags, { tag: "keep", path: "guide/install.md" }];
    expect(withoutTag(two, { tag: "onboarding", path: "guide/install.md" })).toEqual(["keep"]);
  });
});
