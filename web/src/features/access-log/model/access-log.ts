import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import {
  parseFacet,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";
import { messages } from "../messages";

export type AccessEvent = components["schemas"]["AccessEventSummary"];
export type AccessLogPage = components["schemas"]["AccessLogPage"];
export type Change = AccessEvent["change"];

/** Every change the log records, in the order the filter offers them. */
export const CHANGES = [
  "granted",
  "revoked",
  "ownership_transferred",
  "library_created",
  "library_deleted",
] as const satisfies readonly Change[];
const LIBRARY_ID = /^\/[^/\s]+\/[^/\s]+$/;

/** Every library's log (operators) and one library's (its admins): newest first, no other sort. */
export const ACCESS_LOG_TABLE: TableConfig = { id: "access-log", sortFields: [] };
export const LIBRARY_ACCESS_LOG_TABLE: TableConfig = { id: "library-access-log", sortFields: [] };

/** What the URL holds: the changes to show, (operators' log) one library, the page and its size. */
export interface AccessLogView extends TableSearch {
  change?: Change[] | undefined;
  library?: string | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseAccessLogView(search: Record<string, unknown>): AccessLogView {
  // The log has no text filter and one order: only the page and its size are kept.
  const { page, size } = parseTableSearch(search, ACCESS_LOG_TABLE);
  const library = typeof search.library === "string" ? search.library.trim() : "";
  return {
    page,
    size,
    change: parseFacet(search.change, CHANGES),
    library: LIBRARY_ID.test(library) ? library : undefined,
  };
}

/** A library's own log filters by change only. */
export function parseLibraryAccessLogView(search: Record<string, unknown>): AccessLogView {
  const { page, size } = parseTableSearch(search, LIBRARY_ACCESS_LOG_TABLE);
  return { page, size, change: parseFacet(search.change, CHANGES) };
}

/** Whether a library ID typed into the operators' filter is one the API accepts. */
export const isLibraryId = (text: string) => LIBRARY_ID.test(text.trim());

/** What `GET .../access-log` filters by: the view without its page and size. */
export interface AccessLogFilters {
  change?: readonly string[];
  library?: string;
}

export const accessLogFilters = (view: AccessLogView): AccessLogFilters => ({
  ...(view.change && { change: view.change }),
  ...(view.library && { library: view.library }),
});

/** The query string of `GET .../access-log` for some filters and one request's page. */
export function accessLogParams(
  filters: AccessLogFilters,
  limit: number,
  cursor?: string | null,
): string {
  const p = new URLSearchParams({ limit: String(limit) });
  for (const change of filters.change ?? []) p.append("change", change);
  if (filters.library) p.set("library", filters.library);
  if (cursor) p.set("cursor", cursor);
  return p.toString();
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
