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
      manual: article.manual_tags,
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

  it("shows a tag both declared and set by hand in both places", () => {
    const groups = tagGroups({
      tags: ["setup"],
      front_matter: { tags: ["setup"] },
      manual_tags: [{ tag: "setup", path: "a.md" }],
    });
    expect(groups.frontMatter).toEqual(["setup"]);
    expect(groups.manual).toHaveLength(1);
    expect(groups.rules).toEqual([]);
  });
});

describe("editing manual tags", () => {
  it("adds a tag to the path's own manual tags only, normalized", () => {
    expect(tagsSetOn(article.manual_tags, "guide/install.md")).toEqual(["onboarding"]);
    expect(addTag(article.manual_tags, "guide/install.md", "  Getting Started ")).toEqual({
      ok: true,
      tag: "getting-started",
      tags: ["onboarding", "getting-started"],
    });
  });

  it("refuses a value that is no tag, a duplicate and a 21st tag", () => {
    expect(addTag([], "a.md", "#nope")).toEqual({ ok: false, reason: "invalid" });
    expect(addTag([], "a.md", "   ")).toEqual({ ok: false, reason: "invalid" });
    expect(addTag(article.manual_tags, "guide/install.md", "ONBOARDING")).toEqual({
      ok: false,
      reason: "duplicate",
    });
    const full = Array.from({ length: 20 }, (_, i) => ({ tag: `t${i}`, path: "a.md" }));
    expect(addTag(full, "a.md", "one-more")).toEqual({ ok: false, reason: "too-many" });
  });

  it("removes a tag on the path it was set on, keeping that path's others", () => {
    expect(withoutTag(article.manual_tags, { tag: "legacy", path: "old/install.md" })).toEqual([]);
    const two = [...article.manual_tags, { tag: "keep", path: "guide/install.md" }];
    expect(withoutTag(two, { tag: "onboarding", path: "guide/install.md" })).toEqual(["keep"]);
  });
});
