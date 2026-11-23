import type { ComponentType, ReactNode } from "react";
import type { components } from "@/shared/lib/api-schema";
import {
  type CredentialKind,
  explainInvalidCredential,
  hostKeyChanged,
  refusedCredential,
} from "@/shared/lib/credentials";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language, messagesFor } from "@/shared/lib/i18n";
import {
  filledRules,
  lines,
  type TagRuleDraft,
  tagRuleHint,
  validatePatterns,
  validateRule,
} from "@/shared/lib/path-selection";
import { errorMessages } from "../messages/errors";
import { pageMessages } from "../messages/page";
import { pathsMessages } from "../messages/paths";
import { sharedMessages } from "../messages/shared";
import { syncMessages } from "../messages/sync";

export type SettingsLibrary = components["schemas"]["LibraryDetail"];
export type SettingsVersion = components["schemas"]["VersionOut"];
export type VersionList = components["schemas"]["VersionList"];
export type AddedVersion = components["schemas"]["AddedVersion"];
export type SyncedLibrary = components["schemas"]["SyncedLibrary"];
export type SyncedVersion = components["schemas"]["SyncedVersion"];
export type ReimportedVersion = components["schemas"]["ReimportedVersion"];
export type RemovalResult = components["schemas"]["RemovalResult"];
export type SavedSettings = components["schemas"]["UpdatedLibrarySettings"];
type SettingsIn = components["schemas"]["LibrarySettingsIn"];
export type JobList = components["schemas"]["JobList"];
export type ReprocessJob = components["schemas"]["JobSummary"];
export type LibraryAccess = components["schemas"]["LibraryAccess"];

const MAX_TITLE = 200;
export const MAX_DESCRIPTION = 1000;

/** What went wrong, and where it belongs: next to a field, or in the section's alert. */
export interface Problem {
  field?: "title" | "description" | "ref" | "paths" | "tags" | "credential" | "mode";
  message: string;
  /** A wait state, not a mistake: shown neutral instead of red. */
  tone?: "info";
  /** The way out is another part of this page (a refused version is a branch to re-sync). */
  jump?: { href: `#${string}`; label: string };
  link?: { href: "/sign-in" | "/setup"; label: string };
  /** Asking again would get the same answer (a moved tag moved back): offer no retry. */
  final?: boolean;
}

export interface DetailsDraft {
  title: string;
  description: string;
}

/** The checks that need no server. A title is one line, 1 to 200 characters; a description may be empty. */
export function validateDetails(
  { title, description }: DetailsDraft,
  language: Language = currentLanguage(),
) {
  const m = messagesFor(pageMessages, language).details;
  const t = title.trim();
  return {
    title: !t ? m.noTitle : t.length > MAX_TITLE ? m.titleTooLong(MAX_TITLE) : undefined,
    description:
      description.trim().length > MAX_DESCRIPTION
        ? m.descriptionTooLong(MAX_DESCRIPTION)
        : undefined,
  };
}

/** Only what changed is sent, so an untouched field keeps following the README. */
export function changedFields(saved: DetailsDraft, draft: DetailsDraft) {
  const patch: { title?: string; description?: string } = {};
  if (draft.title.trim() !== saved.title) patch.title = draft.title.trim();
  if (draft.description.trim() !== saved.description) patch.description = draft.description.trim();
  return patch;
}

type Errors = (typeof errorMessages)[Language];

const offline = (m: Errors): Problem => ({ message: m.offline });

const session = (error: HttpError, m: Errors): Problem | undefined => {
  if (error.status === 401) {
    return { message: m.sessionEnded, link: { href: "/sign-in", label: m.signIn } };
  }
  if (error.status === 403 && error.code === "setup_required") {
    return { message: m.noAdmin, link: { href: "/setup", label: m.setUp } };
  }
  if (error.status === 403) return { message: m.notAllowed };
  return undefined;
};

const generic = (error: HttpError, m: Errors): Problem => ({ message: m.generic(error.status) });

export function explainSave(error: unknown, language: Language = currentLanguage()): Problem {
  const m = messagesFor(errorMessages, language);
  if (!(error instanceof HttpError)) return offline(m);
  const gone = session(error, m);
  if (gone) return gone;
  if (error.status === 404) return { message: m.gone };
  if (error.status === 422) {
    const field = error.fields
      .flatMap((f) => f.loc)
      .find((l) => l === "title" || l === "description");
    return field === "title" || field === "description"
      ? { field, message: error.fields[0]?.msg ?? m.refusedValue }
      : { message: m.refusedForm };
  }
  return generic(error, m);
}

/** The profiles an override may name could not be read. */
export function explainProfilesError(
  error: unknown,
  language: Language = currentLanguage(),
): string {
  const m = messagesFor(errorMessages, language);
  const words = error instanceof HttpError ? session(error, m)?.message : m.offline;
  return m.profiles(words);
}

/** A refused retrieval save: a mode that can't run, a profile that's gone, a budget too high. */
export function explainRetrievalSave(
  error: unknown,
  language: Language = currentLanguage(),
): Problem {
  const m = messagesFor(errorMessages, language);
  if (!(error instanceof HttpError)) return offline(m);
  const gone = session(error, m);
  if (gone) return gone;
  switch (error.code) {
    case "mode_unavailable":
      return { field: "mode", message: error.message };
    case "unknown_provider":
    case "provider_unsupported":
    case "invalid_model":
    case "budget_above_instance":
    case "thinking_unsupported":
      return { message: error.message };
    case "not_found":
      return { message: m.gone };
  }
  if (error.status === 422) return { message: m.refusedForm };
  return generic(error, m);
}

/** `sent`: the kind of token or key the request carried to replace the stored one, if any. */
export function explainAddVersion(
  error: unknown,
  ref: string,
  sent?: CredentialKind,
  language: Language = currentLanguage(),
): Problem {
  const m = messagesFor(errorMessages, language);
  const a = m.addVersion;
  if (!(error instanceof HttpError)) return offline(m);
  const gone = session(error, m);
  if (gone) return gone;
  switch (error.code) {
    case "not_found":
      return { message: m.gone };
    case "version_exists":
      return {
        field: "ref",
        message: a.exists(ref),
        jump: { href: "#sync-heading", label: a.resyncBranches },
      };
    case "version_importing":
      return { field: "ref", message: a.importing(ref) };
    case "commit_already_imported":
      return {
        field: "ref",
        message: a.sameText(
          error.message.startsWith("Request to") ? a.commitImported : error.message,
        ),
      };
    case "unknown_ref":
      return { field: "ref", message: a.unknownRef(ref) };
    case "ambiguous_ref":
      return { field: "ref", message: a.ambiguousRef(ref) };
    case "credentials_required":
      return { field: "credential", message: a.credentialsUnreadable };
    case "repository_auth_required":
      return {
        field: "credential",
        message: sent ? refusedCredential(sent, language) : a.authRequired,
      };
    case "invalid_credential":
      return { field: "credential", message: explainInvalidCredential(error.message, language) };
    case "host_key_changed":
      return { message: hostKeyChanged(language) };
    default:
      return error.status === 422 ? { message: a.refused } : generic(error, m);
  }
}

export function explainSync(error: unknown, language: Language = currentLanguage()): Problem {
  const m = messagesFor(errorMessages, language);
  if (!(error instanceof HttpError)) return offline(m);
  const gone = session(error, m);
  if (gone) return gone;
  if (error.status === 404) return { message: m.gone };
  if (error.status === 409) return { tone: "info", message: m.sync.stillImporting };
  if (error.status === 422 && error.code === "auth_failed") return { message: m.sync.authFailed };
  if (error.status === 422 && error.code === "host_key_changed") {
    return { message: m.sync.hostKeyChanged };
  }
  if (error.status === 422) return { message: m.sync.unreadable };
  return generic(error, m);
}

/** Why confirming a moved tag did not queue its re-import. */
export function explainReimport(error: unknown, language: Language = currentLanguage()): Problem {
  const m = messagesFor(errorMessages, language);
  const r = m.reimport;
  if (!(error instanceof HttpError)) return offline(m);
  const gone = session(error, m);
  if (gone) return gone;
  switch (error.code) {
    case "not_found":
      return { final: true, message: r.versionGone };
    case "tag_not_moved":
      return { tone: "info", final: true, message: r.tagNotMoved };
    case "version_importing":
      return { tone: "info", message: r.importing };
    case "ref_deleted":
      return { final: true, message: r.tagDeleted };
    case "not_a_tag":
      return { final: true, message: r.notATag };
    case "host_key_changed":
      return { message: r.hostKeyChanged };
    case "credentials_required":
    case "repository_auth_required":
      return { message: r.credentials };
    default:
      return error.status === 422 ? { message: r.unreadable } : generic(error, m);
  }
}

/** The row a confirmed re-import turns a `tag_moved` failure into: its import is queued. */
export const reimportedRow = (v: SyncedVersion, r: ReimportedVersion): SyncedVersion => ({
  ...v,
  status: "queued",
  previous_commit_sha: r.previous_commit_sha,
  commit_sha: r.commit_sha,
  job_id: r.job_id,
  error_code: null,
  error: null,
});

/** `what` is “version v1.3.0” or “this library”, in the same language (`remove` in the errors). */
export function explainRemove(
  error: unknown,
  what: string,
  language: Language = currentLanguage(),
): Problem {
  const m = messagesFor(errorMessages, language);
  if (!(error instanceof HttpError)) return offline(m);
  const gone = session(error, m);
  if (gone) return gone;
  if (error.code === "import_in_progress") return { message: m.remove.importRunning(what) };
  return generic(error, m);
}

/** Removed elsewhere already: the row should go either way. */
export const isAlreadyGone = (error: unknown) => error instanceof HttpError && error.status === 404;

export const statusWords = (
  s: SyncedVersion["status"],
  language: Language = currentLanguage(),
): string => messagesFor(syncMessages, language).status[s];

/** Why a `failed` version could not be synced, by its stable `error_code`. */
export function failureWords(v: SyncedVersion, language: Language = currentLanguage()): string {
  const m = messagesFor(syncMessages, language).failure;
  switch (v.error_code) {
    case "ref_deleted":
      return v.ref_kind === "tag" ? m.tagDeleted : m.branchDeleted;
    case "tag_moved":
      return m.tagMoved;
    case "unexpected":
      return m.unexpected;
    default:
      return m.other;
  }
}

/** One sentence for the whole re-sync, so the outcome reads before the per-version rows. */
export function syncHeadline(
  result: SyncedLibrary,
  language: Language = currentLanguage(),
): string {
  const m = messagesFor(syncMessages, language).headline;
  const count = (s: SyncedVersion["status"]) =>
    result.versions.filter((v) => v.status === s).length;
  const queued = count("queued");
  const failed = count("failed");
  if (queued > 0 || failed > 0) return m.changes(queued, failed);
  if (count("importing") > 0) return m.importing;
  if (result.versions.length > 0 && count("pinned") === result.versions.length) {
    return m.allPinned;
  }
  return m.upToDate;
}

export const shortSha = (sha: string) => sha.slice(0, 7);

/** The views of the libraries slice, handed in by the route (a feature never imports another). */
export interface JobViews {
  /** The full import view: heading, progress, skipped files; `finish` replaces its buttons. */
  Import: ComponentType<{ added: AddedVersion; finish: ReactNode }>;
  /** One job as a compact line with its bar. */
  Line: ComponentType<{ jobId: string; label: string }>;
  /** The Preview button and the files these paths take in one version of the repository. */
  Preview: ComponentType<{
    url: string;
    version: string | null;
    include: string;
    exclude: string;
  }>;
}

/** The last action a section started; the others clear their own notices when it is not theirs. */
export interface Activity {
  by: string;
  n: number;
}

/** A library's paths and tag rules as the settings form holds them. */
export interface SelectionDraft {
  include: string;
  exclude: string;
  rules: TagRuleDraft[];
}

type StoredSelection = Pick<SavedSettings, "include_paths" | "exclude_paths" | "tag_rules">;

/** The form for what is stored: one pattern per line, one row per rule. */
export const draftOf = (stored: StoredSelection): SelectionDraft => ({
  include: stored.include_paths.join("\n"),
  exclude: stored.exclude_paths.join("\n"),
  rules: stored.tag_rules.map((r, key) => ({ key, pattern: r.pattern, tag: r.tag })),
});

/**
 * The paths and tag rules as a whole set, as `PUT …/settings` takes them: what is left out is
 * cleared. `chunking` is left out on purpose: the server then keeps the stored one.
 */
export const settingsOf = (draft: SelectionDraft): Required<Omit<SettingsIn, "chunking">> => ({
  include_paths: lines(draft.include),
  exclude_paths: lines(draft.exclude),
  tag_rules: filledRules(draft.rules).map((r) => ({
    pattern: r.pattern.trim(),
    tag: r.tag.trim(),
  })),
});

const same = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((x, i) => x === b[i]);

/**
 * `API` and `api` are one tag, so letter case alone is no change. Only the server makes the tag
 * (case folding, spaces as `-`): a spelling this still takes for a change saves the rules again,
 * and the server finds nothing to re-tag.
 */
const ruleKey = (r: { pattern: string; tag: string }) =>
  `${r.pattern.trim()}\u0000${r.tag.trim().toLowerCase()}`;

/**
 * What saving the form would ask of every version: `paths` (fetched and imported again), `tags`
 * (only re-tagged from what is stored) or null (nothing changed, nothing to save).
 */
export function selectionChange(
  stored: StoredSelection,
  draft: SelectionDraft,
): "paths" | "tags" | null {
  const next = settingsOf(draft);
  if (!same(next.include_paths, stored.include_paths)) return "paths";
  if (!same(next.exclude_paths, stored.exclude_paths)) return "paths";
  return same(next.tag_rules.map(ruleKey), stored.tag_rules.map(ruleKey)) ? null : "tags";
}

/** The checks that need no server: a bad path line, and whether some rule is wrong. */
export function validateSelection(draft: SelectionDraft, language: Language = currentLanguage()) {
  const paths =
    validatePatterns(draft.include, language) ?? validatePatterns(draft.exclude, language);
  const badRule = filledRules(draft.rules).find((r) => {
    const p = validateRule(r, language);
    return Boolean(p.pattern || p.tag);
  });
  return { paths, badRule };
}

/** The first `max` refs, comma-separated, and how many more there are. */
export const listed = (
  refs: readonly string[],
  language: Language = currentLanguage(),
  max = 5,
): string =>
  messagesFor(sharedMessages, language).andMore(
    refs.slice(0, max).join(", "),
    Math.max(0, refs.length - max),
  );

/** What the server runs for an edit: re-import (`paths`), re-chunk (`chunking`) or re-tag (`tags`). */
export type SettingsChange = "paths" | "chunking" | "tags";

/** The warning before saving: every version is re-processed, and what that means for this change. */
export function reprocessWarning(
  change: SettingsChange,
  refs: readonly string[],
  afterFailure = false,
  language: Language = currentLanguage(),
) {
  const m = messagesFor(pathsMessages, language).warning;
  const list = listed(refs, language);
  const which = refs.length === 1 ? m.one[change](list) : m.every[change](refs.length, list);
  const what =
    change === "tags"
      ? m.tags(which)
      : change === "chunking"
        ? m.chunking(which)
        : afterFailure
          ? m.pathsAfterFailure(which)
          : m.paths(which);
  return { title: m.title[change], what, safe: m.safe, confirm: m.confirm[change] };
}

/** The job each change queues, by how much it redoes: a wider one does all a narrower one does. */
const JOBS: Partial<Record<string, { change: SettingsChange; reach: number }>> = {
  retag: { change: "tags", reach: 1 },
  rechunk: { change: "chunking", reach: 2 },
  reprocess: { change: "paths", reach: 3 },
};
const reachOf = (job: Pick<ReprocessJob, "kind"> | undefined) =>
  (job && JOBS[job.kind]?.reach) ?? 0;

type JobState = Pick<ReprocessJob, "kind" | "state">;

/**
 * The widest re-processing that failed and was not redone since, as the server finds it
 * (`UpdateLibrarySettings`): `jobs` newest first. A failed job is redone by a later job of the
 * same or a greater reach that did not fail (it succeeded, or is queued or running), so a failed
 * `reprocess` stays unhealed after a `retag` or a `rechunk`.
 */
export function unhealedJob<J extends JobState>(jobs: readonly J[] | null | undefined) {
  let covered = 0;
  let worst: J | undefined;
  for (const job of jobs ?? []) {
    const reach = reachOf(job);
    if (reach === 0) continue;
    if (job.state !== "failed") covered = Math.max(covered, reach);
    else if (reach > covered && reach > reachOf(worst)) worst = job;
  }
  return worst;
}

/**
 * What the server will run for this change: the change itself, or the widest failed
 * re-processing not redone since when that is wider (a smaller job would hide the failure). A
 * tag-only edit after a failed `reprocess` re-runs the full re-processing (it re-tags too), even
 * when a `retag` or a `rechunk` succeeded in between; after a failed `rechunk`, the re-chunking.
 */
export function effectiveChange(
  change: "paths" | "tags",
  jobs: readonly JobState[] | null | undefined,
): { change: SettingsChange; afterFailure: boolean } {
  const failed = unhealedJob(jobs);
  const pending = failed && JOBS[failed.kind];
  const own = reachOf({ kind: change === "paths" ? "reprocess" : "retag" });
  const runs = pending && pending.reach > own ? pending.change : change;
  return {
    change: runs,
    // Only when this save runs that same failed re-chunk or re-process again: a paths edit after a
    // failed re-chunk is a re-process of its own, and is not worded as a re-run.
    afterFailure: pending !== undefined && pending.reach > 1 && pending.change === runs,
  };
}

/** Why the paths and tag rules were not saved. Nothing is stored after a refusal. */
export function explainSettings(error: unknown, language: Language = currentLanguage()): Problem {
  const m = messagesFor(errorMessages, language);
  if (!(error instanceof HttpError)) return offline(m);
  const gone = session(error, m);
  if (gone) return gone;
  switch (error.code) {
    case "not_found":
      return { message: m.gone };
    case "invalid_path_pattern":
      return { field: "paths", message: m.settings.invalidPath };
    case "invalid_tag":
      return { field: "tags", message: m.settings.invalidTag(tagRuleHint(language)) };
    default:
      return error.status === 422 ? { message: m.settings.refused } : generic(error, m);
  }
}

/** One sentence for what saving did, so it reads before the job's own line. */
export function savedHeadline(
  saved: SavedSettings,
  language: Language = currentLanguage(),
): string {
  const m = messagesFor(pathsMessages, language).headline;
  if (saved.job_id === null) return saved.versions.length === 0 ? m.noVersion : m.unchanged;
  if (saved.reprocess === "tags") return m.tags;
  if (saved.reprocess === "chunking") return m.chunking;
  return m.paths;
}

/** Next to Save: what pressing it would do. */
export function saveHint(
  change: SavedSettings["reprocess"],
  versions: number,
  language: Language = currentLanguage(),
): string {
  const m = messagesFor(pathsMessages, language).hint;
  if (change === null) return m.unchanged;
  return versions === 0 ? m.noVersion : m.confirm;
}
