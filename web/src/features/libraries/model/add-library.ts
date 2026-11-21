import type { components } from "@/shared/lib/api-schema";
import {
  type CredentialKind,
  explainInvalidCredential,
  HOST_KEY_CHANGED,
  refusedCredential,
} from "@/shared/lib/credentials";
import { HttpError } from "@/shared/lib/http";
import {
  filledRules,
  lines,
  TAG_RULE_HINT,
  type TagRuleDraft,
  validatePatterns,
  validateRule,
} from "@/shared/lib/path-selection";

export type CheckedRepository = components["schemas"]["CheckedRepository"];
export type AddedLibrary = components["schemas"]["AddedLibrary"];
export type AddLibraryCommand = components["schemas"]["AddLibraryCommand"];
type ProblemCode = components["schemas"]["ProblemCode"];
export type FileProblem = components["schemas"]["FileProblemSummary"];
export type RepositoryPreview = components["schemas"]["RepositoryPreview"];
export type Context7 = components["schemas"]["Context7Out"];
export type PreviewCommand = components["schemas"]["PreviewRepositoryCommand"];
export type AddedVersion = components["schemas"]["AddedVersion"];

/** Where a failed request belongs in the form: next to the field it is about, else the alert. */
export type AddField = "url" | "credential" | "id" | "ref" | "paths" | "tags";
export interface AddProblem {
  field?: AddField;
  message: string;
  /** The session is gone or the server is not set up: the way out is another page. */
  link?: { href: "/sign-in" | "/setup"; label: string };
  /** The library this repository already is (`/owner/repo`): the field links to it. */
  library?: string;
}

/** `https://github.com/acme/payments` or `git@host:org/repo.git`, no credentials. */
const MAX_URL_LENGTH = 2048;

export function validateUrl(raw: string): string | undefined {
  const url = raw.trim();
  if (!url) return "Paste the address of a git repository.";
  if (url.length > MAX_URL_LENGTH)
    return "That address is too long. Addresses can be up to 2048 characters.";
  if (/\s/.test(url)) return "An address has no spaces. Paste it again.";
  if (/^[a-z][a-z0-9+.-]*:\/\/[^/@]*@/i.test(url) && !/^ssh:\/\/git@/i.test(url)) {
    return "Remove the username and password from the address. For a private repository, give its token under “This repository is private”.";
  }
  if (!/^(https?:\/\/|ssh:\/\/|file:\/\/|[\w.-]+@[\w.-]+:)/i.test(url)) {
    return "That isn't a repository address yet. Start with https://, like https://github.com/acme/payments.";
  }
  return undefined;
}

export function validateLibraryId(raw: string): string | undefined {
  if (!/^\/[^/\s]+\/[^/\s]+$/.test(raw.trim())) {
    return "Use the form /owner/repo, like /acme/payments.";
  }
  return undefined;
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

/**
 * The address step: what to tell a person who pasted a URL that does not work. `sent` is the
 * kind of credential the request carried, if any: a refused login means something else then.
 */
export function explainCheckError(error: unknown, sent?: CredentialKind): AddProblem {
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
      return sent
        ? { field: "credential", message: refusedCredential(sent) }
        : {
            field: "credential",
            message:
              "That repository asks for a login. If it is private, give a token or deploy key that can read it.",
          };
    case "invalid_credential":
      return { field: "credential", message: explainInvalidCredential(error.message) };
    case "host_key_changed":
      return { message: HOST_KEY_CHANGED };
    case "repository_unreachable":
      return {
        field: "url",
        message: "Couldn't reach that address. Check it, and that the server can get online.",
      };
    case "git_not_installed":
      return { message: "The server has no git installed, so it can't read repositories." };
    case "library_id_taken":
      // The check refuses before it reads anything: the ID this address proposes is in use.
      // Only the IDs collide; that library may come from another host, so say no more than that.
      return error.libraryId
        ? {
            field: "url",
            message: `A library with this repository's ID, ${error.libraryId}, already exists.`,
            library: error.libraryId,
          }
        : { field: "url", message: "A library with this repository's ID already exists." };
    default:
      return generic(error);
  }
}

/** `preview_busy`: the server is reading other repositories; say how long to wait when it did. */
const busy = (error: HttpError, what: string): AddProblem => ({
  message: `The server is busy ${what}. Try again in ${
    error.retryAfter
      ? `${error.retryAfter} ${error.retryAfter === 1 ? "second" : "seconds"}`
      : "a moment"
  }.`,
});

/** The submit step. */
export function explainAddError(
  error: unknown,
  ref: string | null,
  sent?: CredentialKind,
): AddProblem {
  if (!(error instanceof HttpError)) return OFFLINE;
  const gone = session(error);
  if (gone) return gone;
  switch (error.code) {
    case "preview_busy":
      return busy(
        error,
        "reading other repositories, so it couldn't read this one's context7.json",
      );
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
        message: `A tag isn't valid. ${TAG_RULE_HINT}`,
      };
    case "invalid_repository_url":
    case "not_a_git_repository":
    case "repository_unreachable":
      return { ...explainCheckError(error), field: "url" };
    case "repository_auth_required":
    case "invalid_credential":
    case "host_key_changed":
      return explainCheckError(error, sent);
    case "no_articles":
      return {
        field: "paths",
        message:
          "No Markdown files match these paths. Widen them, or clear them to take every .md and .mdx file.",
      };
    default:
      return error.status === 422
        ? { message: "Check the form and try again. The server refused something in it." }
        : generic(error);
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
  unparsable: "Couldn't be parsed or split into chunks",
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

/** The checks that need no server: what is wrong with the form as it stands. */
export function validateForm(form: {
  libraryId: string;
  include: string;
  exclude: string;
  rules: readonly TagRuleDraft[];
}) {
  const id = validateLibraryId(form.libraryId);
  const paths = validatePatterns(form.include) ?? validatePatterns(form.exclude);
  const badRule = filledRules(form.rules).some((r) => {
    const p = validateRule(r);
    return Boolean(p.pattern || p.tag);
  });
  return { id, paths, badRule, ok: !id && !paths && !badRule };
}

/** `1000` listed and a truncation marker: the real count is higher, so say "1000+". */
export const skippedLabel = (summary: ProblemSummary) =>
  summary.truncated ? `${summary.skipped}+` : String(summary.skipped);

/** The preview step: the same refusals as an add (minus the ID), and a busy server. */
export function explainPreviewError(
  error: unknown,
  ref: string | null,
  sent?: CredentialKind,
): AddProblem {
  if (error instanceof HttpError && error.code === "preview_busy") {
    return busy(error, "previewing other repositories");
  }
  return explainAddError(error, ref, sent);
}

/** Why an older version ticked in the preview was not queued, and whether trying again can help. */
export function explainOlderVersionError(
  error: unknown,
  tag: string,
): { message: string; retry: boolean } {
  if (error instanceof HttpError) {
    switch (error.code) {
      case "version_importing":
        return { message: "Already being imported.", retry: false };
      case "version_exists":
        return { message: "Already a version of this library.", retry: false };
      case "commit_already_imported": {
        // The server names the version: "commit … is already the version 'v1.4.0' of library …".
        const other = /the version ['"](.+?)['"] of library/.exec(error.message)?.[1];
        return {
          message: other
            ? `Same commit as version ${other}, already imported.`
            : "Same commit as a version already imported.",
          retry: false,
        };
      }
    }
  }
  // Offline, a busy or failing server: worth another go. A refusal about the tag itself is not.
  const retry = !(error instanceof HttpError) || error.status >= 500 || error.status === 429;
  return { message: explainAddError(error, tag).message, retry };
}

/** What a preview was asked for; a different one means the result on screen is out of date. */
export const previewKey = (form: {
  url: string;
  ref: string | null;
  include: string;
  exclude: string;
}) => JSON.stringify([form.url, form.ref, lines(form.include), lines(form.exclude)]);

/** A folder of the preview tree: its own files, its subfolders, and how many files sit below it. */
export interface PreviewFolder {
  /** Shown name; a chain of folders holding only one folder reads as one (`docs/guides`). */
  name: string;
  /** Repository-relative, unique: a React key. */
  path: string;
  folders: PreviewFolder[];
  files: string[];
  count: number;
}

interface Building {
  folders: Map<string, Building>;
  files: string[];
}

function finish(name: string, path: string, node: Building): PreviewFolder {
  const folders = [...node.folders.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([child, sub]) => finish(child, path ? `${path}/${child}` : child, sub));
  const count = node.files.length + folders.reduce((n, f) => n + f.count, 0);
  const only = folders[0];
  // A folder with nothing but one folder in it would be a row that says nothing: merge them.
  if (name && node.files.length === 0 && folders.length === 1 && only) {
    return { ...only, name: `${name}/${only.name}` };
  }
  return { name, path, folders, files: [...node.files].sort((a, b) => a.localeCompare(b)), count };
}

/** Repository paths as a folder tree (the root has an empty name); files keep only their name. */
export function buildFileTree(paths: readonly string[]): PreviewFolder {
  const root: Building = { folders: new Map(), files: [] };
  for (const path of paths) {
    const parts = path.split("/");
    const file = parts.pop() ?? path;
    let node = root;
    for (const part of parts) {
      let next = node.folders.get(part);
      if (!next) {
        next = { folders: new Map(), files: [] };
        node.folders.set(part, next);
      }
      node = next;
    }
    node.files.push(file);
  }
  // The root has no name, so it is never merged into its only folder.
  return finish("", "", root);
}

const files = (n: number) => `${n.toLocaleString("en-US")} ${n === 1 ? "file" : "files"}`;

/** The headline of a preview: how many files an import would take, and whether all are listed. */
export function previewCountText(
  preview: Pick<RepositoryPreview, "total" | "truncated" | "files">,
) {
  if (preview.total === 0) return "No Markdown files match.";
  const match = `${files(preview.total)} ${preview.total === 1 ? "matches" : "match"}.`;
  return preview.truncated
    ? `${match} The first ${preview.files.length.toLocaleString("en-US")} are listed.`
    : match;
}
