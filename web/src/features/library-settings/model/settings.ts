import type { ComponentType, ReactNode } from "react";
import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";

export type SettingsLibrary = components["schemas"]["LibraryDetail"];
export type SettingsVersion = components["schemas"]["VersionOut"];
export type AddedVersion = components["schemas"]["AddedVersion"];
export type SyncedLibrary = components["schemas"]["SyncedLibrary"];
export type SyncedVersion = components["schemas"]["SyncedVersion"];
export type RemovalResult = components["schemas"]["RemovalResult"];

const MAX_TITLE = 200;
export const MAX_DESCRIPTION = 1000;

/** What went wrong, and where it belongs: next to a field, or in the section's alert. */
export interface Problem {
  field?: "title" | "description" | "ref";
  message: string;
  /** A wait state, not a mistake: shown neutral instead of red. */
  tone?: "info";
  /** The way out is another part of this page (a refused version is a branch to re-sync). */
  jump?: { href: `#${string}`; label: string };
  link?: { href: "/sign-in" | "/setup"; label: string };
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

const sentence = (text: string) =>
  `${text.replace(/\.$/, "")}, so a second version would hold the same text.`;

export function explainAddVersion(error: unknown, ref: string): Problem {
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
        message:
          "This repository is private and needs credentials. Adding them from the web UI is not available yet.",
      };
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
  if (error.status === 422) {
    return {
      message:
        "The repository couldn't be read, so nothing changed. Every version keeps what it served.",
    };
  }
  return generic(error);
}

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
};
export const statusWords = (s: SyncedVersion["status"]) => STATUS_WORDS[s];

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

/** The job views of the libraries slice, handed in by the route (a feature never imports another). */
export interface JobViews {
  /** The full import view: heading, progress, skipped files; `finish` replaces its buttons. */
  Import: ComponentType<{ added: AddedVersion; finish: ReactNode }>;
  /** One job as a compact line with its bar. */
  Line: ComponentType<{ jobId: string; label: string }>;
}

/** The last action a section started; the others clear their own notices when it is not theirs. */
export interface Activity {
  by: string;
  n: number;
}
