import { describe, expect, it } from "vitest";
import { parseTags, toggleTag, visibleTags } from "./tags";

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
