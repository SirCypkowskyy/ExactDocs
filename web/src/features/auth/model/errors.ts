import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import { messages } from "../messages";
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
export function explainSignInRefusal(
  code: unknown,
  language: Language = currentLanguage(),
): string | undefined {
  const t = messages[language].refusal;
  if (typeof code === "string") {
    const github =
      /^(github_app_not_approved|github_sso_required|github_access_denied):([a-zA-Z0-9][a-zA-Z0-9-]{0,99})$/.exec(
        code,
      );
    if (github) {
      const organization = github[2] ?? "";
      if (github[1] === "github_app_not_approved") {
        return t.appNotApproved(organization);
      }
      if (github[1] === "github_sso_required") {
        return t.ssoRequired(organization);
      }
      return t.orgDenied(organization);
    }
  }
  switch (code) {
    case "github_team_required":
      return t.teamRequired;
    case "github_org_required":
      return t.orgRequired;
    case "provider_access_revoked":
      return t.revoked;
    case "not_allowed":
      return t.notAllowed;
    case "account_disabled":
      return t.disabled;
    case "username_unavailable":
      return t.usernameTaken;
    case "provider_unavailable":
      return t.providerDown;
    case "sign_in_cancelled":
      return t.cancelled;
    case "sign_in_failed":
      return t.failed;
    case "not_linked":
      return t.notLinked;
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
export function explainError(error: unknown, language: Language = currentLanguage()): FormProblem {
  const t = messages[language].errors;
  if (error instanceof AdminCreated) {
    return { message: t.adminCreated, link: { href: "/sign-in", label: t.signIn } };
  }
  if (!(error instanceof HttpError)) {
    return { message: t.unreachable };
  }
  if (error.code === "invalid_credentials") {
    return { message: t.invalidCredentials };
  }
  if (error.code === "rate_limited") {
    const wait = error.retryAfter;
    return { message: t.tooMany(wait === undefined ? t.waitLittle : t.tryAgainIn(wait)) };
  }
  if (error.code === "already_set_up") {
    return { message: t.alreadySetUp, link: { href: "/sign-in", label: t.signInInstead } };
  }
  if (error.code === "setup_required") {
    return { message: t.setupRequired, link: { href: "/setup", label: t.setItUp } };
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
  return { message: t.server(error.status) };
}
