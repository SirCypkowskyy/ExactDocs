import { HttpError } from "@/shared/lib/http";
import type { FieldErrors } from "./session";

export interface FormProblem {
  /** Shown in the alert above the form. */
  message?: string;
  fields?: FieldErrors;
  /** A way out of the problem: a plain link after the message. */
  link?: { href: "/sign-in" | "/setup"; label: string };
}

/**
 * Why an external sign-in came back refused (`/sign-in?error=<code>`), in words a person can act
 * on. Only known codes are shown: the query string is not trusted to say anything else.
 */
export function explainSignInRefusal(code: unknown): string | undefined {
  if (typeof code === "string") {
    const github =
      /^(github_app_not_approved|github_sso_required|github_access_denied):([a-zA-Z0-9][a-zA-Z0-9-]{0,99})$/.exec(
        code,
      );
    if (github) {
      const organization = github[2];
      if (github[1] === "github_app_not_approved") {
        return `The organization ${organization} has not approved this app. Ask an organization owner to approve the ExactDocs OAuth App in GitHub settings.`;
      }
      if (github[1] === "github_sso_required") {
        return `Please authorize SSO for ${organization}. Authorize the ExactDocs OAuth App for your organization in GitHub settings, then try again.`;
      }
      return `The organization ${organization} refused access. Ask an organization owner to check the ExactDocs OAuth App permissions.`;
    }
  }
  switch (code) {
    case "github_team_required":
      return "You are not a member of an allowed team. Ask an organization owner to add you to a team allowed to use this server.";
    case "github_org_required":
      return "You are not a member of an allowed organization. Ask an organization owner to check your membership.";
    case "provider_access_revoked":
      return "Your identity provider revoked this sign-in. Sign in again to authorize access.";
    case "not_allowed":
      return "Your identity provider signed you in, but you are not in a group allowed to use this server. Ask an admin to add you.";
    case "account_disabled":
      return "Your account is disabled. Ask an admin to enable it.";
    case "username_unavailable":
      return "No account could be created for you: your username is taken. Ask an admin for help.";
    case "provider_unavailable":
      return "Your identity provider can't be reached right now. Try again in a moment, or sign in with a password.";
    case "sign_in_cancelled":
      return "Your identity provider did not sign you in. Try again.";
    case "sign_in_failed":
      return "The sign-in could not be completed. Start it again from this page.";
    default:
      return undefined;
  }
}

/** Setup succeeded but the sign-in that follows it did not: the admin exists, a retry would 409. */
export class AdminCreated extends Error {
  constructor() {
    super("admin created, sign-in failed");
    this.name = "AdminCreated";
  }
}

/** Turn a failed request into words a person can act on. */
export function explainError(error: unknown): FormProblem {
  if (error instanceof AdminCreated) {
    return {
      message: "The admin account was created, but signing in failed.",
      link: { href: "/sign-in", label: "Sign in" },
    };
  }
  if (!(error instanceof HttpError)) {
    return { message: "Can't reach the server. Check your connection and try again." };
  }
  if (error.code === "invalid_credentials") {
    return { message: "That username and password don't match." };
  }
  if (error.code === "rate_limited") {
    const wait = error.retryAfter;
    const when =
      wait === undefined
        ? "Wait a little, then try again."
        : `Try again in ${wait} ${wait === 1 ? "second" : "seconds"}.`;
    return { message: `Too many failed sign-ins. ${when}` };
  }
  if (error.code === "already_set_up") {
    return {
      message: "This server already has an admin.",
      link: { href: "/sign-in", label: "Sign in instead" },
    };
  }
  if (error.code === "setup_required") {
    return {
      message: "This server has no admin yet.",
      link: { href: "/setup", label: "Set it up" },
    };
  }
  if (error.code === "invalid_username") return { fields: { username: error.message } };
  if (error.status === 422 && error.fields.length > 0) {
    const fields: FieldErrors = {};
    for (const f of error.fields) {
      const name = f.loc.at(-1);
      if (name === "username" || name === "password") fields[name] ??= f.msg;
    }
    if (Object.keys(fields).length > 0) return { fields };
  }
  return {
    message: `Something went wrong on the server (${error.status}). Try again in a moment.`,
  };
}
