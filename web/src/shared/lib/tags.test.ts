import { describe, expect, it } from "vitest";
import { isTagShaped, parseTags, toggleTag, visibleTags } from "./tags";

describe("tags", () => {
  it("parses and toggles without caring about case", () => {
    expect(parseTags("api, guide,,")).toEqual(["api", "guide"]);
    expect(toggleTag(["api"], "guide")).toBe("api,guide");
    expect(toggleTag(["api"], "API")).toBeUndefined();
  });

  it("drops what the API would refuse: tags over 100 characters and past the 20th", () => {
    expect(parseTags(`ok,${"x".repeat(101)}`)).toEqual(["ok"]);
    const many = Array.from({ length: 30 }, (_, i) => `t${i}`).join(",");
    expect(parseTags(many)).toHaveLength(20);
  });
});

describe("visibleTags", () => {
  it("keeps every selected tag on screen, even one ranked far down", () => {
    const facets = Array.from({ length: 30 }, (_, i) => `t${i}`);
    const shown = visibleTags(["t25"], facets, 5);
    expect(shown).toHaveLength(5);
    expect(shown[0]).toBe("t25");
    expect(shown.filter((t) => t === "t25")).toHaveLength(1);
    expect(visibleTags(["Gone"], ["a"], 5)).toEqual(["Gone", "a"]);
  });
});

describe("isTagShaped", () => {
  it("tells whether a value has a tag's shape, without making the tag", () => {
    expect(isTagShaped("  Getting   Started ")).toBe(true);
    expect(isTagShaped("ｖ２")).toBe(true);
    expect(isTagShaped("c++")).toBe(true);
    expect(isTagShaped("हिन्दी")).toBe(true);
    expect(isTagShaped("Straße")).toBe(true);
    expect(isTagShaped("-lead")).toBe(false);
    expect(isTagShaped("a,b")).toBe(false);
    expect(isTagShaped("🙂")).toBe(false);
    expect(isTagShaped("x".repeat(40))).toBe(true);
    expect(isTagShaped("x".repeat(41))).toBe(false);
    expect(isTagShaped("")).toBe(false);
  });

  it("splits on whitespace as the server's str.split() does", () => {
    for (const sep of ["\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\u2028", "\u3000", "\t"]) {
      expect(isTagShaped(`a${sep}b`)).toBe(true);
      expect(isTagShaped(`${sep}ab${sep}`)).toBe(true);
    }
    // U+FEFF is whitespace to JavaScript but not to Python: the server refuses it.
    expect(isTagShaped("\ufeffab")).toBe(false);
    expect(isTagShaped("a\ufeffb")).toBe(false);
  });
});
