// A library's file selection and tag rules as typed in a form: the add form and the settings page share them.
import { currentLanguage, defineMessages, type Language } from "./i18n";
import { isTagShaped } from "./tags";

/** What the path and tag rule checks say. Paths and patterns stay as typed. */
const messages = defineMessages(
  {
    absolute: (pattern: string) =>
      `“${pattern}” starts with /. Paths are relative to the repository root, like docs/.`,
    parent: (pattern: string) => `“${pattern}” uses “..”. Paths stay inside the repository.`,
    tagRuleHint:
      "Start with a letter or digit, then letters, digits, spaces and . + - _ (40 characters at most).",
    pathMissing: "Add a path, like docs/api/**.",
    pathOutside: "Use a path inside the repository, like docs/api/**.",
    tagMissing: "Add a tag, like api.",
  },
  {
    absolute: (pattern) =>
      `„${pattern}” zaczyna się od /. Ścieżki są względne wobec katalogu głównego repozytorium, np. docs/.`,
    parent: (pattern) => `„${pattern}” zawiera „..”. Ścieżki muszą pozostać wewnątrz repozytorium.`,
    tagRuleHint:
      "Zacznij od litery lub cyfry, potem używaj liter, cyfr, spacji oraz . + - _ (najwyżej 40 znaków).",
    pathMissing: "Dodaj ścieżkę, np. docs/api/**.",
    pathOutside: "Użyj ścieżki wewnątrz repozytorium, np. docs/api/**.",
    tagMissing: "Dodaj tag, np. api.",
  },
);

/** Most tag rules a library may have (the API's limit). */
export const MAX_TAG_RULES = 64;

/** The non-blank lines of a text box, trimmed: one pattern each. */
export const lines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

/** Patterns are repo-relative: never absolute, never `..`. Returns the first bad line. */
export function validatePatterns(
  text: string,
  language: Language = currentLanguage(),
): string | undefined {
  const t = messages[language];
  for (const pattern of lines(text)) {
    if (pattern.startsWith("/")) return t.absolute(pattern);
    if (pattern.split("/").includes("..")) return t.parent(pattern);
  }
  return undefined;
}

export interface TagRuleDraft {
  key: number;
  pattern: string;
  tag: string;
}

/** What a tag may look like; the server stores it normalized (`Getting Started` is `getting-started`). */
export const tagRuleHint = (language: Language = currentLanguage()) =>
  messages[language].tagRuleHint;

export function validateRule(
  rule: TagRuleDraft,
  language: Language = currentLanguage(),
): { pattern?: string; tag?: string } {
  const t = messages[language];
  const problems: { pattern?: string; tag?: string } = {};
  const pattern = rule.pattern.trim();
  const tag = rule.tag.trim();
  if (!pattern) problems.pattern = t.pathMissing;
  else if (pattern.startsWith("/") || pattern.split("/").includes("..")) {
    problems.pattern = t.pathOutside;
  }
  if (!tag) problems.tag = t.tagMissing;
  else if (!isTagShaped(tag)) {
    problems.tag = t.tagRuleHint;
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
