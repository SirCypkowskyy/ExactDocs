import { describe, expect, it } from "vitest";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import { normalizeQuery } from "@/shared/lib/search-query";
import { searchQueryOptions } from "../api/search-queries";
import { countLabel, highlightPieces } from "./search";

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

  it("copes with unsorted spans, CRLF and combining marks", () => {
    const pieces = highlightPieces("a\r\nb e\u0301x", [
      { start: 5, end: 7 },
      { start: 3, end: 4 },
    ]);
    expect(pieces.map((p) => [p.text, p.hit])).toEqual([
      ["a\r\n", false],
      ["b", true],
      [" ", false],
      ["e\u0301", true],
      ["x", false],
    ]);
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

describe("cache key", () => {
  it("changes with the commit, so a re-import never shows old hits", () => {
    const base = {
      owner: "a",
      repo: "b",
      ref: "v1",
      q: "x",
      tags: undefined,
      match: "any",
    } as const;
    expect(searchQueryOptions({ ...base, sha: "111" }).queryKey).not.toEqual(
      searchQueryOptions({ ...base, sha: "222" }).queryKey,
    );
    expect(searchQueryOptions({ ...base, sha: "111" }).queryKey[0]).toBe(BROWSE_KEY[0]);
  });
});

describe("limits", () => {
  it("normalizes the query and caps the tags", () => {
    expect(normalizeQuery("   ")).toBeUndefined();
    expect(normalizeQuery("  retry ")).toBe("retry");
    expect(normalizeQuery("x".repeat(1500))).toHaveLength(1000);
    // 999 letters then an emoji (2 UTF-16 units): the cap must not cut the pair in half.
    const capped = normalizeQuery(`${"x".repeat(999)}🚀🚀`) ?? "";
    expect(Array.from(capped)).toHaveLength(1000);
    expect(() => encodeURIComponent(capped)).not.toThrow();
  });

  it("words the count once", () => {
    expect(countLabel(1, "a", "v1", true)).toBe("1 result for “a” in v1");
    expect(countLabel(20, "a", "v1", false)).toBe("Top 20 results for “a” in v1");
    expect(countLabel(0, "a", "v1", true)).toBe("No results for “a” in v1");
  });
});
