import { describe, expect, it } from "vitest";
import { tagRuleHint, validatePatterns, validateRule } from "./path-selection";

describe("path and tag rule checks", () => {
  it("say what is wrong in English, naming the pattern", () => {
    expect(validatePatterns("docs/\n/etc", "en")).toBe(
      "“/etc” starts with /. Paths are relative to the repository root, like docs/.",
    );
    expect(validateRule({ key: 0, pattern: "", tag: "" }, "en")).toEqual({
      pattern: "Add a path, like docs/api/**.",
      tag: "Add a tag, like api.",
    });
  });

  it("say the same in Polish, with Polish quotation marks", () => {
    expect(validatePatterns("docs/../x", "pl")).toBe(
      "„docs/../x” zawiera „..”. Ścieżki muszą pozostać wewnątrz repozytorium.",
    );
    expect(validateRule({ key: 0, pattern: "/abs", tag: "#api" }, "pl")).toEqual({
      pattern: "Użyj ścieżki wewnątrz repozytorium, np. docs/api/**.",
      tag: tagRuleHint("pl"),
    });
    expect(tagRuleHint("pl")).toMatch(/najwyżej 40 znaków/);
  });
});
