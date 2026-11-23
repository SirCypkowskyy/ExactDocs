import type { components } from "@/shared/lib/api-schema";
import { HttpError, type Query } from "@/shared/lib/http";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import { messages } from "../messages";

export type AccessEvent = components["schemas"]["AccessEventSummary"];
export type AccessLogPage = components["schemas"]["AccessLogPage"];
export type Change = AccessEvent["change"];

/** Every change the log records, in the order the filter offers them. */
const CHANGES = [
  "granted",
  "revoked",
  "ownership_transferred",
  "library_created",
  "library_deleted",
] as const satisfies readonly Change[];
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
    change: (CHANGES as readonly string[]).includes(change) ? (change as Change) : undefined,
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
export function describeEvent(event: AccessEvent, language: Language = currentLanguage()): Part[] {
  const t = messages[language].sentence;
  // Words a language does without (English needs no "user" before a name) leave no part.
  const words = (key: string, text: string): Part[] => (text ? [{ key, text }] : []);
  const actor: Part[] = event.actor
    ? [...words("actor-before", t.actorBefore), { key: "actor", text: event.actor, kind: "person" }]
    : [{ key: "actor", text: t.instance }];
  const subject: Part[] =
    event.kind === "group"
      ? [
          ...words("the-group", t.theGroup),
          { key: "subject", text: event.subject ?? "", kind: "group" },
        ]
      : [
          ...words("the-user", t.theUser),
          { key: "subject", text: event.subject ?? "", kind: "person" },
        ];
  const roleName = (role: string) => t.roles[role] ?? role;
  const role: Part = { key: "role", text: roleName(event.role ?? ""), kind: "role" };
  switch (event.change) {
    case "library_created":
      return [...actor, ...words("verb", t.created)];
    case "library_deleted":
      return [...actor, ...words("verb", t.deleted)];
    case "ownership_transferred":
      return [...actor, ...words("verb", t.transferred), ...subject];
    case "revoked":
      return [
        ...actor,
        ...words("verb", t.revoked),
        role,
        ...words("from", t.revokedFrom),
        ...subject,
      ];
    case "granted":
      if (event.previous_role) {
        return [
          ...actor,
          ...words("verb", t.changed),
          ...subject,
          ...words("from", t.changedFrom),
          { key: "previous", text: roleName(event.previous_role), kind: "role" },
          ...words("to", t.changedTo),
          role,
        ];
      }
      return [
        ...actor,
        ...words("verb", t.gave),
        ...subject,
        ...words("the", t.gaveThe),
        role,
        ...words("tail", t.gaveTail),
      ];
  }
}

/** One sentence a person can act on, for any failure of the access log API. */
export function explainAccessLogError(
  error: unknown,
  language: Language = currentLanguage(),
): string {
  const t = messages[language].errors;
  if (!(error instanceof HttpError)) return t.offline;
  if (error.status === 401) return t.sessionEnded;
  if (error.status === 403) return t.forbidden;
  if (error.status === 404) return t.notFound;
  if (error.code === "invalid_cursor") return t.invalidCursor;
  return t.other(error.status);
}

/** A library's own log filters by change only. */
export function parseLibraryAccessLogView(search: Record<string, unknown>): AccessLogView {
  const { change } = parseAccessLogView(search);
  return change ? { change } : {};
}
