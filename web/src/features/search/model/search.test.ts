import { describe, expect, it } from "vitest";
import { countLabel, highlightPieces, normalizeQuery, sendableTags } from "./search";

describe("highlightPieces", () => {
  it("cuts the snippet at the offsets", () => {
    expect(highlightPieces("set retry_policy now", [{ start: 4, end: 16 }])).toEqual([
      { at: 0, text: "set ", hit: false },
      { at: 4, text: "retry_policy", hit: true },
      { at: 16, text: " now", hit: false },
    ]);
  });

  it("counts characters, not UTF-16 units: an emoji before the match does not shift it", () => {
    const pieces = highlightPieces("🚀 retry", [{ start: 2, end: 7 }]);
    expect(pieces.filter((p) => p.hit).map((p) => p.text)).toEqual(["retry"]);
  });

  it("merges overlaps, clips out-of-range spans and keeps markup as text", () => {
    const pieces = highlightPieces("<b>a</b>", [
      { start: 0, end: 4 },
      { start: 3, end: 99 },
      { start: 5, end: 5 },
    ]);
    expect(pieces).toEqual([{ at: 0, text: "<b>a</b>", hit: true }]);
    expect(highlightPieces("abc", [])).toEqual([{ at: 0, text: "abc", hit: false }]);
  });
});

describe("limits", () => {
  it("normalizes the query and caps the tags", () => {
    expect(normalizeQuery("   ")).toBeUndefined();
    expect(normalizeQuery("  retry ")).toBe("retry");
    expect(normalizeQuery("x".repeat(1500))).toHaveLength(1000);
    expect(sendableTags(Array.from({ length: 30 }, (_, i) => `t${i}`))).toHaveLength(20);
    expect(sendableTags(["ok", "x".repeat(101)])).toEqual(["ok"]);
  });

  it("words the count once", () => {
    expect(countLabel(1, "a", "v1", true)).toBe("1 result for “a” in v1");
    expect(countLabel(20, "a", "v1", false)).toBe("Top 20 results for “a” in v1");
    expect(countLabel(0, "a", "v1", true)).toBe("No results for “a” in v1");
  });
});
