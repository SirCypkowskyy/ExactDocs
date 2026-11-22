import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";

export type Grant = components["schemas"]["LibraryGrantSummary"];
export type GrantList = components["schemas"]["LibraryGrantList"];
/** Every grant on the library, as a change answers them. */
export type GrantsNow = components["schemas"]["LibraryGrants"];
export type GrantRequest = components["schemas"]["LibraryGrantRequest"];
export type GrantedRole = GrantRequest["role"];
export type CallerRole = GrantList["caller_role"];
export type SubjectKind = Grant["kind"];

export const ROLE_LABELS: Record<string, string> = {
  viewer: "Viewer",
  contributor: "Contributor",
  admin: "Admin",
  creator: "Creator",
};

/** What each role that can be given adds (the backend's rules, docs/rest-api.md). */
export const ROLE_HINTS: Record<GrantedRole, string> = {
  viewer: "Finds, reads and searches it, in the UI and over MCP.",
  contributor: "Also imports versions, re-syncs it and tags articles.",
  admin: "Also changes its settings, removes versions and shares it.",
};

export const KIND_LABELS: Record<SubjectKind, string> = { user: "User", group: "Group" };

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

/** Whom a grant names, for a sentence: "bob", "the group corp:docs". */
export const who = (grant: Pick<Grant, "kind" | "subject">) =>
  grant.kind === "group" ? `the group ${grant.subject}` : grant.subject;

/** `who` at the start of a sentence: a username keeps its letter case. */
export const whoFirst = (grant: Pick<Grant, "kind" | "subject">) =>
  grant.kind === "group" ? `The group ${grant.subject}` : grant.subject;

/** One sentence a person can act on, for any failure of the sharing API. */
export function explainSharingError(error: unknown): string {
  if (!(error instanceof HttpError)) {
    return "Can't reach the server. Check your connection and try again.";
  }
  switch (error.code) {
    case "forbidden":
      return error.message.includes("creator")
        ? "Only the library's creator can do that: give or take away the admin role, or transfer it."
        : "Only an admin of this library can see or change who it is shared with.";
    case "unknown_account":
      return "No account has that username. Check the spelling, or ask an operator to create it.";
    case "unknown_grant":
      return "That role was already taken away. The list has been refreshed.";
    case "invalid_grant":
      return error.message.includes("already")
        ? "That user is already the creator of this library."
        : "The creator's role isn't changed here. Transfer the library instead.";
    case "not_found":
      return "This library no longer exists, or you can't see it.";
  }
  if (error.status === 401) return "Your session ended. Sign in again to manage sharing.";
  if (error.status === 422) {
    const [first] = error.fields;
    if (first) return `The server refused ${String(first.loc.at(-1))}: ${first.msg}.`;
    return `The server refused the request: ${error.message}.`;
  }
  return `Something went wrong (${error.status}). Try again.`;
}
