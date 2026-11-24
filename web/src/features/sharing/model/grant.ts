import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language, messagesFor } from "@/shared/lib/i18n";
import { messages } from "../messages";

export type Grant = components["schemas"]["LibraryGrantSummary"];
export type GrantList = components["schemas"]["LibraryGrantList"];
/** Every grant on the library, as a change answers them. */
export type GrantsNow = components["schemas"]["LibraryGrants"];
export type GrantRequest = components["schemas"]["LibraryGrantRequest"];
export type GrantedRole = GrantRequest["role"];
export type CallerRole = GrantList["caller_role"];
export type SubjectKind = Grant["kind"];

/** The roles a caller may give: an admin up to contributor, the creator `admin` too. */
export const givableRoles = (caller: CallerRole): GrantedRole[] =>
  caller === "creator" ? ["viewer", "contributor", "admin"] : ["viewer", "contributor"];

/**
 * Whether the caller may change or take away a grant: never the creator's (that is a transfer),
 * an admin's only as the creator. The server checks again.
 */
export function canManage(grant: Grant, caller: CallerRole): boolean {
  if (grant.role === "creator") return false;
  return grant.role !== "admin" || caller === "creator";
}

/** A grant's identity in the table and in a pending change: `kind:subject`. */
export const grantKey = (g: Pick<Grant, "kind" | "subject">) => `${g.kind}:${g.subject}`;

/** One sentence a person can act on, for any failure of the sharing API. */
export function explainSharingError(
  error: unknown,
  language: Language = currentLanguage(),
): string {
  const t = messagesFor(messages, language).errors;
  if (!(error instanceof HttpError)) return t.offline;
  switch (error.code) {
    case "forbidden":
      return error.message.includes("creator") ? t.creatorOnly : t.adminOnly;
    case "unknown_account":
      return t.unknownAccount;
    case "unknown_grant":
      return t.unknownGrant;
    case "invalid_grant":
      return error.message.includes("already") ? t.alreadyCreator : t.creatorRole;
    case "not_found":
      return t.notFound;
  }
  if (error.status === 401) return t.sessionEnded;
  if (error.status === 422) {
    const [first] = error.fields;
    if (first) return t.refusedField(String(first.loc.at(-1)), first.msg);
    return t.refused(error.message);
  }
  return t.other(error.status);
}
