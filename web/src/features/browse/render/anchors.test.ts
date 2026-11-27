import { describe, expect, it } from "vitest";
// A copy of packages/exactdocs/tests/fixtures/heading_anchors.json (the Docker build sees only web/);
// test_chunker.py checks the two are identical and tests the Python chunker against the same table.
import vectors from "./fixtures/heading_anchors.json";
import { headingAnchors } from "./parse";

describe("heading anchors match the chunk anchors", () => {
  it.each(vectors.cases)("$name", ({ markdown, anchors }) => {
    const top = headingAnchors(markdown)
      .filter((h) => h.topLevel)
      .map((h) => h.anchor);
    expect(top).toEqual(anchors);
  });
});

// CodeQL's worst cases for the old attribute-list pattern (exponential): they stay heading text.
describe("a near attribute list", () => {
  it.each([
    `{{-=${"!-=".repeat(5000)}`,
    `{{.${"---=!.".repeat(5000)}`,
    `{{#${"-.-#".repeat(5000)}`,
  ])(
    "fails fast",
    (tail) => {
      const [heading] = headingAnchors(`## T ${tail}\n`);
      expect(heading?.text).toBe(`T ${tail}`);
    },
    5000,
  );
});
