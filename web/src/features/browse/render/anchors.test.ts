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
