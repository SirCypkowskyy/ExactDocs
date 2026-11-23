import type { components } from "@/shared/lib/api-schema";
import { HttpError, type Query } from "@/shared/lib/http";

export type AccessEvent = components["schemas"]["AccessEventSummary"];
export type AccessLogPage = components["schemas"]["AccessLogPage"];
export type Change = AccessEvent["change"];

/** Every change the log records, in the order the filter offers them. */
export const CHANGE_LABELS: Record<Change, string> = {
  granted: "Roles given or changed",
  revoked: "Roles taken away",
  ownership_transferred: "Ownership transfers",
  library_created: "Creations",
  library_deleted: "Removals",
};

const CHANGES = Object.keys(CHANGE_LABELS) as Change[];
const LIBRARY_ID = /^\/[^/\s]+\/[^/\s]+$/;

/** What the URL holds: one change to show, and (operators' log) one library. */
export interface AccessLogView {
  change?: Change | undefined;
  library?: string | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseAccessLogView(search: Record<string, unknown>): AccessLogView {
  const change = typeof search.change === "string" ? search.change : "";
  const library = typeof search.library === "string" ? search.library.trim() : "";
  return {
    change: (CHANGES as string[]).includes(change) ? (change as Change) : undefined,
    library: LIBRARY_ID.test(library) ? library : undefined,
  };
}

/** Whether a library ID typed into the operators' filter is one the API accepts. */
export const isLibraryId = (text: string) => LIBRARY_ID.test(text.trim());

/** The query of `GET .../access-log` for a view and a page cursor. */
export function accessLogQuery(view: AccessLogView, cursor: string | null): Query {
  return { limit: 50, change: view.change, library: view.library, cursor };
}

/**
 * One part of an event's sentence: plain words, or a name set apart (a person, a group, a role).
 * `key` is unique within the sentence.
 */
export type Part = { key: string; text: string; kind?: "person" | "group" | "role" };

/**
 * The event as a sentence, split so names and roles can be set apart:
 * "alice gave bob the viewer role", "alice changed bob from viewer to contributor".
 */
export function describeEvent(event: AccessEvent): Part[] {
  const actor: Part = event.actor
    ? { key: "actor", text: event.actor, kind: "person" }
    : { key: "actor", text: "ExactDocs (command line or a job)" };
  const subject: Part[] =
    event.kind === "group"
      ? [
          { key: "the-group", text: "the group " },
          { key: "subject", text: event.subject ?? "", kind: "group" },
        ]
      : [{ key: "subject", text: event.subject ?? "", kind: "person" }];
  const role: Part = { key: "role", text: event.role ?? "", kind: "role" };
  const words = (key: string, text: string): Part => ({ key, text });
  switch (event.change) {
    case "library_created":
      return [actor, words("verb", " created the library")];
    case "library_deleted":
      return [actor, words("verb", " removed the library and every role on it")];
    case "ownership_transferred":
      return [actor, words("verb", " transferred ownership to "), ...subject];
    case "revoked":
      return [actor, words("verb", " took the "), role, words("from", " role from "), ...subject];
    case "granted":
      if (event.previous_role) {
        return [
          actor,
          words("verb", " changed "),
          ...subject,
          words("from", " from "),
          { key: "previous", text: event.previous_role, kind: "role" },
          words("to", " to "),
          role,
        ];
      }
      return [
        actor,
        words("verb", " gave "),
        ...subject,
        words("the", " the "),
        role,
        words("tail", " role"),
      ];
  }
}

/** One sentence a person can act on, for any failure of the access log API. */
export function explainAccessLogError(error: unknown): string {
  if (!(error instanceof HttpError)) {
    return "Can't reach the server. Check your connection and try again.";
  }
  if (error.status === 401) return "Your session ended. Sign in again to read the access log.";
  if (error.status === 403) {
    return "Only the library's admins and the server's operators can read its access log.";
  }
  if (error.status === 404) return "This library doesn't exist, or you have no access to it.";
  if (error.code === "invalid_cursor") return "The list moved on. Reload the page to start over.";
  return `Something went wrong (${error.status}). Try again.`;
}

/** A library's own log filters by change only. */
export function parseLibraryAccessLogView(search: Record<string, unknown>): AccessLogView {
  const { change } = parseAccessLogView(search);
  return change ? { change } : {};
}
