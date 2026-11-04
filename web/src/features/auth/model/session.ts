import type { components } from "@/shared/lib/api-schema";

export type SessionState = components["schemas"]["SessionState"];
export type Account = components["schemas"]["AccountSummary"];

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

export function validateSignIn({ username, password }: Credentials): FieldErrors {
  const errors: FieldErrors = {};
  if (!username.trim()) errors.username = "Enter your username.";
  if (!password) errors.password = "Enter your password.";
  return errors;
}

export function validateSetup(values: Credentials & { confirm: string }): FieldErrors {
  const errors: FieldErrors = {};
  const username = values.username.trim();
  if (!username) errors.username = "Choose a username.";
  else if (username.length > MAX_USERNAME_LENGTH)
    errors.username = `Use at most ${MAX_USERNAME_LENGTH} characters.`;
  else if (/\s/.test(username)) errors.username = "No spaces, please.";
  if (values.password.length < MIN_PASSWORD_LENGTH)
    errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  else if (values.password.length > MAX_PASSWORD_LENGTH)
    errors.password = `Use at most ${MAX_PASSWORD_LENGTH} characters.`;
  if (values.confirm !== values.password) errors.confirm = "The passwords don't match.";
  return errors;
}
