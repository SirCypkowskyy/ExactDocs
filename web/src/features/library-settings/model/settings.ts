import type { ComponentType, ReactNode } from "react";
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
export function validateDetails({ title, description }: DetailsDraft) {
  const t = title.trim();
  return {
    title: !t
      ? "Give the library a title."
      : t.length > MAX_TITLE
        ? `Titles can be up to ${MAX_TITLE} characters.`
        : undefined,
    description:
      description.trim().length > MAX_DESCRIPTION
        ? `Descriptions can be up to ${MAX_DESCRIPTION} characters.`
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

const OFFLINE: Problem = {
  message: "Can't reach the server. Check your connection and try again.",
};

const session = (error: HttpError): Problem | undefined => {
  if (error.status === 401) {
    return { message: "Your session ended.", link: { href: "/sign-in", label: "Sign in" } };
  }
  if (error.status === 403 && error.code === "setup_required") {
    return {
      message: "This server has no admin yet.",
      link: { href: "/setup", label: "Set it up" },
    };
  }
  if (error.status === 403) return { message: "Your account isn't allowed to change libraries." };
  return undefined;
};

const generic = (error: HttpError): Problem => ({
  message: `Something went wrong on the server (${error.status}). Try again in a moment.`,
});

const GONE = "This library no longer exists. It may have been removed in another window.";

export function explainSave(error: unknown): Problem {
  if (!(error instanceof HttpError)) return OFFLINE;
  const gone = session(error);
  if (gone) return gone;
  if (error.status === 404) return { message: GONE };
  if (error.status === 422) {
    const field = error.fields
      .flatMap((f) => f.loc)
      .find((l) => l === "title" || l === "description");
    return field === "title" || field === "description"
      ? { field, message: error.fields[0]?.msg ?? "The server refused that value." }
      : { message: "The server refused something in the form. Check it and try again." };
  }
  return generic(error);
}

/** The profiles an override may name could not be read. */
export function explainProfilesError(error: unknown): string {
  const words = error instanceof HttpError ? session(error)?.message : OFFLINE.message;
  return `${words ?? "The AI profiles could not be read."} Overrides keep what they have; try again to change them.`;
}

/** A refused retrieval save: a mode that can't run, a profile that's gone, a budget too high. */
export function explainRetrievalSave(error: unknown): Problem {
  if (!(error instanceof HttpError)) return OFFLINE;
  const gone = session(error);
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
      return { message: GONE };
  }
  if (error.status === 422) {
    return { message: "The server refused something in the form. Check it and try again." };
  }
  return generic(error);
}

const sentence = (text: string) =>
  `${text.replace(/\.$/, "")}, so a second version would hold the same text.`;

/** `sent`: the kind of token or key the request carried to replace the stored one, if any. */
export function explainAddVersion(error: unknown, ref: string, sent?: CredentialKind): Problem {
  if (!(error instanceof HttpError)) return OFFLINE;
  const gone = session(error);
  if (gone) return gone;
  switch (error.code) {
    case "not_found":
      return { message: GONE };
    case "version_exists":
      return {
        field: "ref",
        message: `“${ref}” is already a version of this library.`,
        jump: { href: "#sync-heading", label: "Branches can be updated with Re-sync" },
      };
    case "version_importing":
      return {
        field: "ref",
        message: `“${ref}” is being imported right now. Wait for it to finish.`,
      };
    case "commit_already_imported":
      return {
        field: "ref",
        message: sentence(
          error.message.startsWith("Request to")
            ? "This commit is already imported under another version"
            : error.message,
        ),
      };
    case "unknown_ref":
      return { field: "ref", message: `This repository has no branch, tag or commit “${ref}”.` };
    case "ambiguous_ref":
      return {
        field: "ref",
        message: `“${ref}” starts more than one commit. Type more characters of the SHA.`,
      };
    case "credentials_required":
      return {
        field: "credential",
        message:
          "The token or key stored for this library can't be read any more (the server's secret key changed). Enter it again to add this version: it replaces the stored one.",
      };
    case "repository_auth_required":
      return {
        field: "credential",
        message: sent
          ? refusedCredential(sent)
          : "The repository asks for a login that this library doesn't have, or no longer works. Enter a token or deploy key that can read it: it replaces the stored one.",
      };
    case "invalid_credential":
      return { field: "credential", message: explainInvalidCredential(error.message) };
    case "host_key_changed":
      return { message: HOST_KEY_CHANGED };
    default:
      return error.status === 422
        ? { message: "The server refused that version. Check it and try again." }
        : generic(error);
  }
}

export function explainSync(error: unknown): Problem {
  if (!(error instanceof HttpError)) return OFFLINE;
  const gone = session(error);
  if (gone) return gone;
  if (error.status === 404) return { message: GONE };
  if (error.status === 409) {
    return {
      tone: "info",
      message:
        "A version is still importing, so there is nothing new to queue. Re-sync once it finishes.",
    };
  }
  if (error.status === 422 && error.code === "auth_failed") {
    return {
      message:
        "The stored credentials were refused or can't be read, so nothing changed: send the token or key again. Every version keeps what it served.",
    };
  }
  if (error.status === 422 && error.code === "host_key_changed") {
    return {
      message:
        "The SSH host key of the repository's server has changed since it was first seen, so nothing was fetched. Check with whoever runs that server before trusting the new key. Every version keeps what it served.",
    };
  }
  if (error.status === 422) {
    return {
      message:
        "The repository couldn't be read (deleted, made private or unreachable), so nothing changed. Every version keeps what it served.",
    };
  }
  return generic(error);
}

/** Why confirming a moved tag did not queue its re-import. */
export function explainReimport(error: unknown): Problem {
  if (!(error instanceof HttpError)) return OFFLINE;
  const gone = session(error);
  if (gone) return gone;
  switch (error.code) {
    case "not_found":
      return {
        final: true,
        message: "This version no longer exists. It may have been removed in another window.",
      };
    case "tag_not_moved":
      return {
        tone: "info",
        final: true,
        message:
          "The tag points at the commit this version serves again, so there is nothing to re-import.",
      };
    case "version_importing":
      return { tone: "info", message: "This version is being imported right now." };
    case "ref_deleted":
      return {
        final: true,
        message: "The tag is gone from the repository now. The version keeps serving what it had.",
      };
    case "not_a_tag":
      return {
        final: true,
        message: "Only a tag is re-imported this way: a branch is updated with Re-sync.",
      };
    case "host_key_changed":
      return {
        message:
          "The SSH host key of the repository's server has changed since it was first seen, so nothing was fetched. Check with whoever runs that server before trusting the new key. The version keeps serving what it had.",
      };
    case "credentials_required":
    case "repository_auth_required":
      return {
        message:
          "The stored credentials were refused or can't be read, so nothing changed. The version keeps serving what it had.",
      };
    default:
      return error.status === 422
        ? {
            message:
              "The repository couldn't be read, so nothing changed. The version keeps serving what it had.",
          }
        : generic(error);
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

/** `what` is “version v1.3.0” or “this library”. */
export function explainRemove(error: unknown, what: string): Problem {
  if (!(error instanceof HttpError)) return OFFLINE;
  const gone = session(error);
  if (gone) return gone;
  if (error.code === "import_in_progress") {
    return {
      message: `An import is still running for ${what}. Removing never cancels a job: try again when it finishes.`,
    };
  }
  return generic(error);
}

/** Removed elsewhere already: the row should go either way. */
export const isAlreadyGone = (error: unknown) => error instanceof HttpError && error.status === 404;

const STATUS_WORDS: Record<SyncedVersion["status"], string> = {
  queued: "Updating",
  up_to_date: "Up to date",
  importing: "Already importing",
  pinned: "Pinned",
  failed: "Failed",
  cancelled: "Left alone: its sync was cancelled",
};
export const statusWords = (s: SyncedVersion["status"]) => STATUS_WORDS[s];

/** Why a `failed` version could not be synced, by its stable `error_code`. */
export function failureWords(v: SyncedVersion): string {
  const kept = "The version keeps serving what it had.";
  switch (v.error_code) {
    case "ref_deleted":
      return `The ${v.ref_kind === "tag" ? "tag" : "branch"} is gone from the repository. ${kept}`;
    case "tag_moved":
      return `The tag now points at another commit. It is not re-imported unless you confirm it. ${kept}`;
    case "unexpected":
      return `Its import could not be queued. ${kept}`;
    default:
      return `It could not be synced. ${kept}`;
  }
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** One sentence for the whole re-sync, so the outcome reads before the per-version rows. */
export function syncHeadline(result: SyncedLibrary): string {
  const count = (s: SyncedVersion["status"]) =>
    result.versions.filter((v) => v.status === s).length;
  const queued = count("queued");
  const failed = count("failed");
  const parts = [
    queued > 0 && `${plural(queued, "version is", "versions are")} updating`,
    failed > 0 && `${plural(failed, "version", "versions")} could not be checked`,
  ].filter(Boolean);
  if (parts.length > 0) return `${parts.join(", ")}.`;
  if (count("importing") > 0) return "An import is already running.";
  if (result.versions.length > 0 && count("pinned") === result.versions.length) {
    return "Nothing to update: every version is pinned.";
  }
  return "Everything is up to date.";
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
export function validateSelection(draft: SelectionDraft) {
  const paths = validatePatterns(draft.include) ?? validatePatterns(draft.exclude);
  const badRule = filledRules(draft.rules).find((r) => {
    const p = validateRule(r);
    return Boolean(p.pattern || p.tag);
  });
  return { paths, badRule };
}

const listed = (refs: readonly string[], max = 5) =>
  refs.length > max
    ? `${refs.slice(0, max).join(", ")}, and ${refs.length - max} more`
    : refs.join(", ");

/** What the server runs for an edit: re-import (`paths`), re-chunk (`chunking`) or re-tag (`tags`). */
export type SettingsChange = "paths" | "chunking" | "tags";

const VERBS: Record<SettingsChange, string> = {
  paths: "re-processed",
  chunking: "re-chunked",
  tags: "re-tagged",
};

/** The warning before saving: every version is re-processed, and what that means for this change. */
export function reprocessWarning(
  change: SettingsChange,
  refs: readonly string[],
  afterFailure = false,
) {
  const verb = VERBS[change];
  const which =
    refs.length === 1
      ? `Its version (${listed(refs)}) will be ${verb}`
      : `Every version will be ${verb}: all ${refs.length} of them (${listed(refs)})`;
  const what =
    change === "tags"
      ? `${which}. Only the tag rules changed, so each one's articles are tagged again from what is stored, and nothing is fetched. Tags added by hand stay.`
      : change === "chunking"
        ? `${which}. The last re-chunking failed, so this runs it again: each one's stored articles are cut into chunks and tagged again, and nothing is fetched.`
        : afterFailure
          ? `${which}. The last re-processing failed, so this runs it in full: each version is fetched again at the commit it serves and imported with these paths and tag rules; branches are not synced.`
          : `${which}. Each one is fetched again at the commit it serves and imported with the new paths; branches are not synced.`;
  return {
    title:
      change === "paths"
        ? "Re-process every version?"
        : change === "chunking"
          ? "Re-chunk every version?"
          : "Re-tag every version?",
    what,
    safe: "Each version keeps serving what it has now until its new state is complete, then switches at once. A version that cannot be re-processed keeps what it had.",
    confirm:
      change === "paths"
        ? "Save and re-process"
        : change === "chunking"
          ? "Save and re-chunk"
          : "Save and re-tag",
  };
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
export function explainSettings(error: unknown): Problem {
  if (!(error instanceof HttpError)) return OFFLINE;
  const gone = session(error);
  if (gone) return gone;
  switch (error.code) {
    case "not_found":
      return { message: GONE };
    case "invalid_path_pattern":
      return {
        field: "paths",
        message:
          "One of the paths isn't valid. Use folders, files or globs like docs/ or docs/**/*.md.",
      };
    case "invalid_tag":
      return { field: "tags", message: `A tag isn't valid. ${TAG_RULE_HINT}` };
    default:
      return error.status === 422
        ? {
            message:
              "The server refused something in the paths or tag rules. Check them and try again.",
          }
        : generic(error);
  }
}

/** One sentence for what saving did, so it reads before the job's own line. */
export function savedHeadline(saved: SavedSettings): string {
  if (saved.job_id === null) {
    return saved.versions.length === 0
      ? "Saved. The library has no version yet: versions imported from now on use these settings."
      : "Saved. Nothing changed, so nothing is re-processed.";
  }
  if (saved.reprocess === "tags") return "Saved. Every version is being re-tagged.";
  if (saved.reprocess === "chunking") return "Saved. Every version is being re-chunked.";
  return "Saved. Every version is being re-processed.";
}

/** Next to Save: what pressing it would do. */
export function saveHint(change: SavedSettings["reprocess"], versions: number): string {
  if (change === null) return "Nothing changed yet.";
  return versions === 0
    ? "No version is imported yet, so nothing is re-processed."
    : "You'll be asked to confirm: every version is re-processed.";
}
