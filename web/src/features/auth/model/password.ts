import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import { messages } from "../messages";
import { MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, type SessionState } from "./session";

/** The body of `PUT /v1/account/password`. */
export type PasswordChange = components["schemas"]["ChangePasswordCommand"];

/** The three boxes of the form, in the order a person fills (and is sent back to) them. */
export const PASSWORD_FIELDS = ["current", "next", "confirm"] as const;
export type PasswordField = (typeof PASSWORD_FIELDS)[number];
export type PasswordErrors = Partial<Record<PasswordField, string>>;

export interface PasswordValues {
  current: string;
  next: string;
  confirm: string;
}

/** The setup's rules (12 to 1024 characters, typed twice); the server stays the authority. */
export function validatePasswordChange(
  values: PasswordValues,
  language: Language = currentLanguage(),
): PasswordErrors {
  const t = messages[language].validation;
  const errors: PasswordErrors = {};
  if (!values.current) errors.current = messages[language].password.enterCurrent;
  if (values.next.length < MIN_PASSWORD_LENGTH) errors.next = t.atLeast(MIN_PASSWORD_LENGTH);
  else if (values.next.length > MAX_PASSWORD_LENGTH) errors.next = t.atMost(MAX_PASSWORD_LENGTH);
  if (values.confirm !== values.next) errors.confirm = t.mismatch;
  return errors;
}

/** What went wrong with a change, and where: a field's own error, or the alert above the form. */
export interface PasswordProblem {
  message?: string;
  fields?: PasswordErrors;
  link?: { href: "/sign-in"; label: string };
  /** The server says the account has no password (409): the form gives way to the note. */
  external?: boolean;
}

/** A wait in words: seconds under a minute, then minutes, then hours (rounded up). */
export function describeWait(seconds: number, language: Language = currentLanguage()): string {
  const t = messages[language].password.wait;
  if (seconds < 60) return t.seconds(Math.max(1, seconds));
  if (seconds < 3600) return t.minutes(Math.ceil(seconds / 60));
  return t.hours(Math.ceil(seconds / 3600));
}

export function explainPasswordError(
  error: unknown,
  language: Language = currentLanguage(),
): PasswordProblem {
  const t = messages[language].password.errors;
  if (!(error instanceof HttpError)) return { message: messages[language].errors.unreachable };
  if (error.code === "wrong_password") return { fields: { current: t.wrongPassword } };
  if (error.code === "rate_limited") {
    const wait = error.retryAfter;
    return { message: t.tooMany(wait === undefined ? t.waitLittle : describeWait(wait, language)) };
  }
  if (error.code === "external_account") return { message: t.external, external: true };
  if (error.status === 401) {
    return { message: t.sessionEnded, link: { href: "/sign-in", label: t.signIn } };
  }
  if (error.status === 422) {
    const fields: PasswordErrors = {};
    for (const f of error.fields) {
      const name = f.loc.at(-1);
      if (name === "new_password")
        fields.next = t.newRefused(MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH);
      if (name === "current_password") fields.current = messages[language].password.enterCurrent;
    }
    if (Object.keys(fields).length > 0) return { fields };
  }
  return { message: messages[language].errors.server(error.status) };
}

/** How someone without a password signs in, for the note that stands in for the form. */
export function signInMethodNote(
  session: SessionState | undefined,
  language: Language = currentLanguage(),
): string {
  const t = messages[language].password.none;
  if (session?.source === "cloudflare_access") return t.access;
  const providers = session?.providers ?? [];
  const only = providers.length === 1 ? providers[0] : undefined;
  return only ? t.provider(only.display_name) : t.providers;
}

/** The session once the server said its account has no password (409 `external_account`). */
export function withoutPassword(state: SessionState | undefined): SessionState | undefined {
  return state?.account ? { ...state, account: { ...state.account, has_password: false } } : state;
}
