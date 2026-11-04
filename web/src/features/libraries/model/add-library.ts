import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";

export type CheckedRepository = components["schemas"]["CheckedRepository"];
export type RepositoryRefs = components["schemas"]["RepositoryRefs"];
export type AddedLibrary = components["schemas"]["AddedLibrary"];
export type AddLibraryCommand = components["schemas"]["AddLibraryCommand"];
type ProblemCode = components["schemas"]["ProblemCode"];
export type FileProblem = components["schemas"]["FileProblemSummary"];

export const MAX_TAG_RULES = 64;
const MAX_TAG_LENGTH = 40;

/** Where a failed request belongs in the form: next to the field it is about, else the alert. */
export type AddField = "url" | "id" | "ref" | "paths" | "tags";
export interface AddProblem {
  field?: AddField;
  message: string;
  /** The session is gone or the server is not set up: the way out is another page. */
  link?: { href: "/sign-in" | "/setup"; label: string };
}

/** `https://github.com/acme/payments` or `git@host:org/repo.git`, no credentials. */
export function validateUrl(raw: string): string | undefined {
  const url = raw.trim();
  if (!url) return "Paste the address of a git repository.";
  if (/\s/.test(url)) return "An address has no spaces. Paste it again.";
  if (/^[a-z][a-z0-9+.-]*:\/\/[^/@]*@/i.test(url) && !/^ssh:\/\/git@/i.test(url)) {
    return "Remove the username and password from the address. Private repositories are not supported yet.";
  }
  if (!/^(https?:\/\/|ssh:\/\/|file:\/\/|[\w.-]+@[\w.-]+:)/i.test(url)) {
    return "Start with https://, ssh:// or git@host:";
  }
  return undefined;
}

export function validateLibraryId(raw: string): string | undefined {
  if (!/^\/[^/\s]+\/[^/\s]+$/.test(raw.trim())) {
    return "Use the form /owner/repo, like /acme/payments.";
  }
  return undefined;
}

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

const TAG = /^[a-z0-9][a-z0-9.+_-]*$/;

export function validateRule(rule: TagRuleDraft): { pattern?: string; tag?: string } {
  const problems: { pattern?: string; tag?: string } = {};
  const pattern = rule.pattern.trim();
  const tag = rule.tag.trim();
  if (!pattern) problems.pattern = "Add a path, like docs/api/**.";
  else if (pattern.startsWith("/") || pattern.split("/").includes("..")) {
    problems.pattern = "Use a path inside the repository, like docs/api/**.";
  }
  if (!tag) problems.tag = "Add a tag, like api.";
  else if (tag.length > MAX_TAG_LENGTH || !TAG.test(tag)) {
    problems.tag = "Lower-case letters, digits, . + - _ ; up to 40 characters.";
  }
  return problems;
}

/** Rules the user left completely empty are ignored rather than reported. */
export const filledRules = (rules: readonly TagRuleDraft[]) =>
  rules.filter((r) => r.pattern.trim() || r.tag.trim());

/** What the ref picker shows: the default first, then branches, tags, and a free-text escape. */
export type RefChoice =
  | { kind: "default" }
  | { kind: "branch"; name: string }
  | { kind: "tag"; name: string }
  | { kind: "other" };

export const encodeChoice = (c: RefChoice) =>
  c.kind === "default" || c.kind === "other" ? c.kind : `${c.kind}:${c.name}`;

export function decodeChoice(value: string): RefChoice {
  if (value === "other") return { kind: "other" };
  const i = value.indexOf(":");
  if (i > 0) {
    const kind = value.slice(0, i);
    if (kind === "branch" || kind === "tag") return { kind, name: value.slice(i + 1) };
  }
  return { kind: "default" };
}

/** The `ref` to send: null means the default branch. */
export function refToSend(choice: RefChoice, typed: string): string | null {
  if (choice.kind === "other") return typed.trim() || null;
  return choice.kind === "default" ? null : choice.name;
}

export function filterRefs<T extends { name: string }>(refs: readonly T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  return q ? refs.filter((r) => r.name.toLowerCase().includes(q)) : [...refs];
}

const session = (error: HttpError): AddProblem | undefined => {
  if (error.status === 401) {
    return { message: "Your session ended.", link: { href: "/sign-in", label: "Sign in" } };
  }
  if (error.status === 403 && error.code === "setup_required") {
    return {
      message: "This server has no admin yet.",
      link: { href: "/setup", label: "Set it up" },
    };
  }
  if (error.status === 403) {
    return { message: "Your account isn't allowed to add libraries." };
  }
  return undefined;
};

const generic = (error: HttpError): AddProblem => ({
  message: `Something went wrong on the server (${error.status}). Try again in a moment.`,
});
const OFFLINE: AddProblem = {
  message: "Can't reach the server. Check your connection and try again.",
};

/** The address step: what to tell a person who pasted a URL that does not work. */
export function explainCheckError(error: unknown): AddProblem {
  if (!(error instanceof HttpError)) return OFFLINE;
  const gone = session(error);
  if (gone) return gone;
  switch (error.code) {
    case "invalid_repository_url":
      return {
        field: "url",
        message:
          "That doesn't look like a git repository address. Try https://github.com/owner/repo.",
      };
    case "not_a_git_repository":
      return {
        field: "url",
        message: "No git repository there. Check the address; a private repository looks the same.",
      };
    case "repository_auth_required":
      return {
        field: "url",
        message:
          "That repository asks for a login. ExactDocs can only read public repositories for now.",
      };
    case "repository_unreachable":
      return {
        field: "url",
        message: "Couldn't reach that address. Check it, and that the server can get online.",
      };
    case "git_not_installed":
      return { message: "The server has no git installed, so it can't read repositories." };
    default:
      return generic(error);
  }
}

/** The submit step. */
export function explainAddError(error: unknown, ref: string | null): AddProblem {
  if (!(error instanceof HttpError)) return OFFLINE;
  const gone = session(error);
  if (gone) return gone;
  switch (error.code) {
    case "library_id_taken":
      return {
        field: "id",
        message: "That ID is already used by another library. Choose another.",
      };
    case "unknown_ref":
      return {
        field: "ref",
        message: ref
          ? `This repository has no branch, tag or commit “${ref}”.`
          : "This repository has no default branch. Choose a tag or a branch.",
      };
    case "ambiguous_ref":
      return {
        field: "ref",
        message: `“${ref ?? ""}” starts more than one commit. Type more characters of the SHA.`,
      };
    case "invalid_path_pattern":
      return {
        field: "paths",
        message:
          "One of the paths isn't valid. Use folders, files or globs like docs/ or docs/**/*.md.",
      };
    case "invalid_tag":
      return {
        field: "tags",
        message: "A tag isn't valid. Lower-case letters, digits, . + - _ ; up to 40 characters.",
      };
    case "invalid_repository_url":
    case "not_a_git_repository":
    case "repository_auth_required":
    case "repository_unreachable":
      return { ...explainCheckError(error), field: "url" };
    case "no_articles":
      return { message: "That selection has no Markdown files. Widen the paths." };
    default:
      return generic(error);
  }
}

/** One group of skipped files, with the reason in words. Unknown codes fall back to the server's sentence. */
const SKIP_REASONS: Partial<Record<ProblemCode, string>> = {
  binary: "Binary files",
  too_large: "Over the size limit (2 MiB)",
  undecodable: "Not readable as text",
  not_a_file: "Not regular files (symlinks)",
  unreadable: "Couldn't be read",
  bad_file_name: "File names that aren't valid UTF-8",
};

const skipReason = (code: string) => SKIP_REASONS[code as ProblemCode];

export interface SkipGroup {
  code: string;
  label: string;
  /** True when the code is one we have words for; otherwise each file shows the server's sentence. */
  known: boolean;
  files: FileProblem[];
}

export interface ProblemSummary {
  skipGroups: SkipGroup[];
  skipped: number;
  notes: FileProblem[];
  /** More files were skipped than the job lists. */
  truncated: boolean;
}

export function summarizeProblems(problems: readonly FileProblem[]): ProblemSummary {
  const groups = new Map<string, SkipGroup>();
  const notes: FileProblem[] = [];
  let truncated = false;
  for (const p of problems) {
    if (p.code === "truncated") {
      truncated = true;
    } else if (p.is_skip) {
      const label = skipReason(p.code);
      const group = groups.get(p.code) ?? {
        code: p.code,
        label: label ?? "Skipped",
        known: Boolean(label),
        files: [],
      };
      group.files.push(p);
      groups.set(p.code, group);
    } else {
      notes.push(p);
    }
  }
  const skipGroups = [...groups.values()].sort((a, b) => b.files.length - a.files.length);
  return {
    skipGroups,
    skipped: skipGroups.reduce((n, g) => n + g.files.length, 0),
    notes,
    truncated,
  };
}
