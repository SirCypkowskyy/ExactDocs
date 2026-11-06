// A library's file selection and tag rules as typed in a form: the add form and the settings page share them.
import { normalizeTag } from "./tags";

/** Most tag rules a library may have (the API's limit). */
export const MAX_TAG_RULES = 64;

/** The non-blank lines of a text box, trimmed: one pattern each. */
export const lines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

/** Patterns are repo-relative: never absolute, never `..`. Returns the first bad line. */
export function validatePatterns(text: string): string | undefined {
  for (const pattern of lines(text)) {
    if (pattern.startsWith("/"))
      return `“${pattern}” starts with /. Paths are relative to the repository root, like docs/.`;
    if (pattern.split("/").includes(".."))
      return `“${pattern}” uses “..”. Paths stay inside the repository.`;
  }
  return undefined;
}

export interface TagRuleDraft {
  key: number;
  pattern: string;
  tag: string;
}

/** What a tag may look like; the server stores it normalized (`Getting Started` is `getting-started`). */
export const TAG_RULE_HINT =
  "Start with a letter or digit, then letters, digits, spaces and . + - _ (40 characters at most).";

export function validateRule(rule: TagRuleDraft): { pattern?: string; tag?: string } {
  const problems: { pattern?: string; tag?: string } = {};
  const pattern = rule.pattern.trim();
  const tag = rule.tag.trim();
  if (!pattern) problems.pattern = "Add a path, like docs/api/**.";
  else if (pattern.startsWith("/") || pattern.split("/").includes("..")) {
    problems.pattern = "Use a path inside the repository, like docs/api/**.";
  }
  if (!tag) problems.tag = "Add a tag, like api.";
  else if (!normalizeTag(tag)) {
    problems.tag = TAG_RULE_HINT;
  }
  return problems;
}

/** Rules the user left completely empty are ignored rather than reported. */
export const filledRules = (rules: readonly TagRuleDraft[]) =>
  rules.filter((r) => r.pattern.trim() || r.tag.trim());

/** Which path box holds a local mistake (the first one), if any. */
export function badPathBox(include: string, exclude: string): "include" | "exclude" | undefined {
  if (validatePatterns(include)) return "include";
  if (validatePatterns(exclude)) return "exclude";
  return undefined;
}
