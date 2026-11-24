import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import { textParam } from "@/shared/lib/list-sort";
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

/** Every library's log (operators) and one library's (its admins): newest first unless sorted. */
export const ACCESS_LOG_TABLE: TableConfig = {
  id: "access-log",
  sortFields: ["at", "library", "change"],
  defaultSort: "-at",
};
export const LIBRARY_ACCESS_LOG_TABLE: TableConfig = {
  id: "library-access-log",
  sortFields: ["at", "change"],
  defaultSort: "-at",
};

/** "Within" presets of the date filter; a custom range is written `from..to` (days, both kept). */
export const WHEN_PRESETS = ["24h", "7d", "30d"] as const;
export type WhenPreset = (typeof WHEN_PRESETS)[number];
/** A custom range of days, either end open: `2026-11-01..2026-11-20`, `2026-11-01..`, `..2026-11-20`. */
export type DayRange = { from?: string | undefined; to?: string | undefined };

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** A calendar day `YYYY-MM-DD` that exists (no 31 November). */
export function isDay(text: string): boolean {
  if (!DAY.test(text)) return false;
  const [y = 0, m = 0, d = 0] = text.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  return date.getFullYear() === y && date.getMonth() === m - 1 && date.getDate() === d;
}

/** A custom range from the URL's `when`: real days, at least one end, the start not after the end. */
export function parseRange(value: string): DayRange | undefined {
  const match = /^([^.]*)\.\.([^.]*)$/.exec(value);
  if (!match) return undefined;
  const [, from = "", to = ""] = match;
  if (!from && !to) return undefined;
  if ((from && !isDay(from)) || (to && !isDay(to))) return undefined;
  if (from && to && from > to) return undefined;
  return { ...(from && { from }), ...(to && { to }) };
}

/** A range as the URL writes it. */
export const rangeParam = ({ from, to }: DayRange) => `${from ?? ""}..${to ?? ""}`;

/**
 * What the URL holds: the sort, the changes to show, who made them (`actor`), whom they were
 * about (`subject`), when (`when`: a preset or a custom range), (operators' log) one library,
 * the page and its size.
 */
export interface AccessLogView extends TableSearch {
  change?: Change[] | undefined;
  library?: string | undefined;
  actor?: string | undefined;
  subject?: string | undefined;
  when?: WhenPreset | string | undefined;
}

/** A name from the URL: a username, an account ID, a group (a bare number arrives parsed). */
const nameParam = (value: unknown) => textParam(typeof value === "number" ? String(value) : value);

/** A preset, or a custom range that holds. */
function parseWhen(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const text = value.trim();
  if ((WHEN_PRESETS as readonly string[]).includes(text)) return text;
  const range = parseRange(text);
  return range && rangeParam(range);
}

/** What both logs read from the URL. */
function parseCommon(search: Record<string, unknown>, config: TableConfig): AccessLogView {
  // The log has no text filter: `q` is not kept.
  const { sort, page, size } = parseTableSearch(search, config);
  return {
    sort,
    page,
    size,
    change: parseFacet(search.change, CHANGES),
    actor: nameParam(search.actor),
    subject: nameParam(search.subject),
    when: parseWhen(search.when),
  };
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseAccessLogView(search: Record<string, unknown>): AccessLogView {
  const library = typeof search.library === "string" ? search.library.trim() : "";
  return {
    ...parseCommon(search, ACCESS_LOG_TABLE),
    library: LIBRARY_ID.test(library) ? library : undefined,
  };
}

/** A library's own log: no library filter, and no sort by library. */
export function parseLibraryAccessLogView(search: Record<string, unknown>): AccessLogView {
  return parseCommon(search, LIBRARY_ACCESS_LOG_TABLE);
}

/** Whether a library ID typed into the operators' filter is one the API accepts. */
export const isLibraryId = (text: string) => LIBRARY_ID.test(text.trim());

/** What `GET .../access-log` filters and sorts by: the view without its page and size. */
export interface AccessLogFilters {
  sort?: string;
  change?: readonly string[];
  library?: string;
  actor?: string;
  subject?: string;
  at_after?: string;
  at_before?: string;
}

const WITHIN_MS: Record<WhenPreset, number> = {
  "24h": 86_400_000,
  "7d": 7 * 86_400_000,
  "30d": 30 * 86_400_000,
};

/** The start of a day in this browser's time zone, as the API reads it (UTC). */
const startOf = (day: string, plusDays = 0) => {
  const [y = 0, m = 0, d = 0] = day.split("-").map(Number);
  return new Date(y, m - 1, d + plusDays).toISOString();
};

/**
 * The time bounds of `when`. A preset counts back from `now` rounded down to the minute, so the
 * route and the page ask for the same thing; a custom range runs from the start of its first day
 * (`at_after`, included) to the start of the day after its last (`at_before`, excluded), in this
 * browser's time zone.
 */
export function whenBounds(
  when: string | undefined,
  now: number,
): Pick<AccessLogFilters, "at_after" | "at_before"> {
  if (!when) return {};
  if (when in WITHIN_MS) {
    const minute = Math.floor(now / 60_000) * 60_000;
    return { at_after: new Date(minute - WITHIN_MS[when as WhenPreset]).toISOString() };
  }
  const range = parseRange(when);
  return {
    ...(range?.from && { at_after: startOf(range.from) }),
    ...(range?.to && { at_before: startOf(range.to, 1) }),
  };
}

export const accessLogFilters = (
  view: AccessLogView,
  now: number = Date.now(),
): AccessLogFilters => ({
  ...(view.sort && { sort: view.sort }),
  ...(view.change && { change: view.change }),
  ...(view.library && { library: view.library }),
  ...(view.actor && { actor: view.actor }),
  ...(view.subject && { subject: view.subject }),
  ...whenBounds(view.when, now),
});

/** The query string of `GET .../access-log` for some filters and one request's page. */
export function accessLogParams(
  filters: AccessLogFilters,
  limit: number,
  cursor?: string | null,
  offset?: number,
): string {
  const p = new URLSearchParams({ limit: String(limit) });
  if (filters.sort) p.set("sort", filters.sort);
  for (const change of filters.change ?? []) p.append("change", change);
  if (filters.library) p.set("library", filters.library);
  if (filters.actor) p.set("actor", filters.actor);
  if (filters.subject) p.set("subject", filters.subject);
  if (filters.at_after) p.set("at_after", filters.at_after);
  if (filters.at_before) p.set("at_before", filters.at_before);
  // A page by offset (0 to 10000) or after a cursor, never both (422 `cursor_with_offset`). A
  // cursor is made for one sort (another is 422 `invalid_cursor`): the sort is part of the
  // source's key, so a new sort starts again from the first page.
  if (offset !== undefined) p.set("offset", String(offset));
  else if (cursor) p.set("cursor", cursor);
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
