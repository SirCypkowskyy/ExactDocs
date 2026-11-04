import { describe, expect, it } from "vitest";
// The same table the Python chunker is tested with: a search link must land on the heading.
import vectors from "../../../../../packages/exactdocs/tests/fixtures/heading_anchors.json";
import { headingAnchors } from "./parse";

describe("heading anchors match the chunk anchors", () => {
  it.each(vectors.cases)("$name", ({ markdown, anchors }) => {
    const top = headingAnchors(markdown)
      .filter((h) => h.topLevel)
      .map((h) => h.anchor);
    expect(top).toEqual(anchors);
  });
});
