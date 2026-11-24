import type { components } from "@/shared/lib/api-schema";
import {
  type CredentialKind,
  explainInvalidCredential,
  hostKeyChanged,
  refusedCredential,
} from "@/shared/lib/credentials";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import {
  filledRules,
  lines,
  type TagRuleDraft,
  tagRuleHint,
  validatePatterns,
  validateRule,
} from "@/shared/lib/path-selection";
import { addMessages } from "../messages/add";

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

/** The refusals in the language the UI speaks; model code takes it from the component. */
const errorsIn = (language: Language) => addMessages[language].errors;

export function validateUrl(
  raw: string,
  language: Language = currentLanguage(),
): string | undefined {
  const t = errorsIn(language);
  const url = raw.trim();
  if (!url) return t.urlEmpty;
  if (url.length > MAX_URL_LENGTH) return t.urlTooLong;
  if (/\s/.test(url)) return t.urlSpaces;
  if (/^[a-z][a-z0-9+.-]*:\/\/[^/@]*@/i.test(url) && !/^ssh:\/\/git@/i.test(url)) {
    return t.urlCredentials;
  }
  if (!/^(https?:\/\/|ssh:\/\/|file:\/\/|[\w.-]+@[\w.-]+:)/i.test(url)) {
    return t.urlScheme;
  }
  return undefined;
}

export function validateLibraryId(
  raw: string,
  language: Language = currentLanguage(),
): string | undefined {
  if (!/^\/[^/\s]+\/[^/\s]+$/.test(raw.trim())) {
    return errorsIn(language).libraryIdForm;
  }
  return undefined;
}

const session = (error: HttpError, language: Language): AddProblem | undefined => {
  const t = errorsIn(language);
  if (error.status === 401) {
    return { message: t.sessionEnded, link: { href: "/sign-in", label: t.signIn } };
  }
  if (error.status === 403 && error.code === "setup_required") {
    return { message: t.noAdmin, link: { href: "/setup", label: t.setUp } };
  }
  if (error.status === 403) {
    return { message: t.forbidden };
  }
  return undefined;
};

const generic = (error: HttpError, language: Language): AddProblem => ({
  message: errorsIn(language).server(error.status),
});
const offline = (language: Language): AddProblem => ({ message: errorsIn(language).offline });

/**
 * The address step: what to tell a person who pasted a URL that does not work. `sent` is the
 * kind of credential the request carried, if any: a refused login means something else then.
 */
export function explainCheckError(
  error: unknown,
  sent?: CredentialKind,
  language: Language = currentLanguage(),
): AddProblem {
  if (!(error instanceof HttpError)) return offline(language);
  const gone = session(error, language);
  if (gone) return gone;
  const t = errorsIn(language);
  switch (error.code) {
    case "invalid_repository_url":
      return { field: "url", message: t.invalidUrl };
    case "not_a_git_repository":
      return { field: "url", message: t.notARepository };
    case "repository_auth_required":
      return sent
        ? { field: "credential", message: refusedCredential(sent, language) }
        : { field: "credential", message: t.authRequired };
    case "invalid_credential":
      return { field: "credential", message: explainInvalidCredential(error.message, language) };
    case "host_key_changed":
      return { message: hostKeyChanged(language) };
    case "repository_unreachable":
      return { field: "url", message: t.unreachable };
    case "git_not_installed":
      return { message: t.noGit };
    case "library_id_taken":
      // The check refuses before it reads anything: the ID this address proposes is in use.
      // Only the IDs collide; that library may come from another host, so say no more than that.
      return error.libraryId
        ? { field: "url", message: t.idTakenBy(error.libraryId), library: error.libraryId }
        : { field: "url", message: t.idTakenByRepository };
    default:
      return generic(error, language);
  }
}

/** The submit step. */
export function explainAddError(
  error: unknown,
  ref: string | null,
  sent?: CredentialKind,
  language: Language = currentLanguage(),
): AddProblem {
  if (!(error instanceof HttpError)) return offline(language);
  const gone = session(error, language);
  if (gone) return gone;
  const t = errorsIn(language);
  switch (error.code) {
    case "preview_busy":
      // The server is reading other repositories; say how long to wait when it did.
      return { message: t.busyReading(error.retryAfter) };
    case "library_id_taken":
      return { field: "id", message: t.idTaken };
    case "unknown_ref":
      return { field: "ref", message: ref ? t.unknownRef(ref) : t.noDefaultBranch };
    case "ambiguous_ref":
      return { field: "ref", message: t.ambiguousRef(ref ?? "") };
    case "invalid_path_pattern":
      return { field: "paths", message: t.invalidPath };
    case "invalid_tag":
      return { field: "tags", message: t.invalidTag(tagRuleHint(language)) };
    case "invalid_repository_url":
    case "not_a_git_repository":
    case "repository_unreachable":
      return { ...explainCheckError(error, undefined, language), field: "url" };
    case "repository_auth_required":
    case "invalid_credential":
    case "host_key_changed":
      return explainCheckError(error, sent, language);
    case "no_articles":
      return { field: "paths", message: t.noArticles };
    default:
      return error.status === 422 ? { message: t.refused } : generic(error, language);
  }
}

/** The groups of skipped files we have words for; unknown codes fall back to the server's sentence. */
const SKIP_CODES: ReadonlySet<string> = new Set<ProblemCode>([
  "binary",
  "too_large",
  "undecodable",
  "not_a_file",
  "unreadable",
  "bad_file_name",
  "unparsable",
]);

type SkipReasons = (typeof addMessages)["en"]["skipReasons"];
const skipReason = (code: string, language: Language) =>
  SKIP_CODES.has(code) ? addMessages[language].skipReasons[code as keyof SkipReasons] : undefined;

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

export function summarizeProblems(
  problems: readonly FileProblem[],
  language: Language = currentLanguage(),
): ProblemSummary {
  const groups = new Map<string, SkipGroup>();
  const notes: FileProblem[] = [];
  let truncated = false;
  for (const p of problems) {
    if (p.code === "truncated") {
      truncated = true;
    } else if (p.is_skip) {
      const label = skipReason(p.code, language);
      const group = groups.get(p.code) ?? {
        code: p.code,
        label: label ?? addMessages[language].skipReasons.other,
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
export function validateForm(
  form: {
    libraryId: string;
    include: string;
    exclude: string;
    rules: readonly TagRuleDraft[];
  },
  language: Language = currentLanguage(),
) {
  const id = validateLibraryId(form.libraryId, language);
  const paths =
    validatePatterns(form.include, language) ?? validatePatterns(form.exclude, language);
  const badRule = filledRules(form.rules).some((r) => {
    const p = validateRule(r, language);
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
  language: Language = currentLanguage(),
): AddProblem {
  if (error instanceof HttpError && error.code === "preview_busy") {
    return { message: errorsIn(language).busyPreviewing(error.retryAfter) };
  }
  return explainAddError(error, ref, sent, language);
}

/** Why an older version ticked in the preview was not queued, and whether trying again can help. */
export function explainOlderVersionError(
  error: unknown,
  tag: string,
  language: Language = currentLanguage(),
): { message: string; retry: boolean } {
  const t = errorsIn(language);
  if (error instanceof HttpError) {
    switch (error.code) {
      case "version_importing":
        return { message: t.importing, retry: false };
      case "version_exists":
        return { message: t.versionExists, retry: false };
      case "commit_already_imported": {
        // The server names the version: "commit … is already the version 'v1.4.0' of library …".
        const other = /the version ['"](.+?)['"] of library/.exec(error.message)?.[1];
        return { message: other ? t.sameCommitAs(other) : t.sameCommit, retry: false };
      }
    }
  }
  // Offline, a busy or failing server: worth another go. A refusal about the tag itself is not.
  const retry = !(error instanceof HttpError) || error.status >= 500 || error.status === 429;
  return { message: explainAddError(error, tag, undefined, language).message, retry };
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

/** The headline of a preview: how many files an import would take, and whether all are listed. */
export function previewCountText(
  preview: Pick<RepositoryPreview, "total" | "truncated" | "files">,
  language: Language = currentLanguage(),
) {
  const t = addMessages[language].preview;
  if (preview.total === 0) return t.noneMatch;
  const match = t.filesMatch(preview.total);
  return preview.truncated ? `${match} ${t.firstListed(preview.files.length)}` : match;
}
