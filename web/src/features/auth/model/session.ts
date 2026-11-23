import type { components } from "@/shared/lib/api-schema";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import { messages } from "../messages";

export type SessionState = components["schemas"]["SessionState"];
export type Account = components["schemas"]["AccountSummary"];
/** An identity provider the sign-in page offers next to the password form. */
export type SignInProvider = components["schemas"]["SignInProviderSummary"];

// Mirrors the backend's rules (identity/dtos.py, identity/model); the server stays the authority.
export const MIN_PASSWORD_LENGTH = 12;
const MAX_PASSWORD_LENGTH = 1024;
const MAX_USERNAME_LENGTH = 64;

/** Where a visitor may be: behind the session (`app`), or on one of the two public pages. */
export type Area = "app" | "sign-in" | "setup";

export type GuardTarget =
  | { to: "/setup" }
  | { to: "/sign-in"; search: { next?: string | undefined } }
  | { to: "/" };

/**
 * Where to send a visitor whose session is `state` and who is asking for `area` at `here`
 * (path + query). `null` means: stay.
 */
export function resolveGuard(
  state: SessionState["state"],
  area: Area,
  here: string,
): GuardTarget | null {
  if (state === "setup_required") return area === "setup" ? null : { to: "/setup" };
  if (state === "signed_out") {
    if (area === "sign-in") return null;
    return { to: "/sign-in", search: area === "app" ? { next: safeNext(here) } : {} };
  }
  return area === "app" ? null : { to: "/" };
}

/**
 * Accept a return URL only when it is a same-origin path (`/libraries/x?y=1`). Anything else
 * (absolute URLs, `//host`, backslash tricks, the auth pages themselves) is dropped, so the
 * sign-in page can never be used as an open redirect.
 */
export function safeNext(raw: unknown): string | undefined {
  if (typeof raw !== "string" || !raw.startsWith("/") || raw.startsWith("//")) return undefined;
  // biome-ignore lint/suspicious/noControlCharactersInRegex: rejecting control chars is the point
  if (/[\\\u0000-\u001f]/.test(raw)) return undefined;
  const url = new URL(raw, "http://exactdocs.invalid");
  if (url.origin !== "http://exactdocs.invalid") return undefined;
  if (url.pathname === "/sign-in" || url.pathname === "/setup") return undefined;
  return raw;
}

/** The body of both `POST /v1/setup` and `POST /v1/session`. */
export type Credentials = components["schemas"]["CreateFirstAdminCommand"];

export type FieldErrors = Partial<Record<"username" | "password" | "confirm", string>>;

export function validateSignIn(
  { username, password }: Credentials,
  language: Language = currentLanguage(),
): FieldErrors {
  const t = messages[language].validation;
  const errors: FieldErrors = {};
  if (!username.trim()) errors.username = t.enterUsername;
  if (!password) errors.password = t.enterPassword;
  return errors;
}

export function validateSetup(
  values: Credentials & { confirm: string },
  language: Language = currentLanguage(),
): FieldErrors {
  const t = messages[language].validation;
  const errors: FieldErrors = {};
  const username = values.username.trim();
  if (!username) errors.username = t.chooseUsername;
  else if (username.length > MAX_USERNAME_LENGTH) errors.username = t.atMost(MAX_USERNAME_LENGTH);
  else if (/\s/.test(username)) errors.username = t.noSpaces;
  if (values.password.length < MIN_PASSWORD_LENGTH)
    errors.password = t.atLeast(MIN_PASSWORD_LENGTH);
  else if (values.password.length > MAX_PASSWORD_LENGTH)
    errors.password = t.atMost(MAX_PASSWORD_LENGTH);
  if (values.confirm !== values.password) errors.confirm = t.mismatch;
  return errors;
}
