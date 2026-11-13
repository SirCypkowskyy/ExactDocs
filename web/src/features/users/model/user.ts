import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";

export type User = components["schemas"]["UserSummary"];
export type NewUser = components["schemas"]["CreateUserCommand"];
export type Role = NonNullable<NewUser["role"]>;

// Mirrors the backend's rules (identity/constants.py); the server stays the authority.
export const MIN_PASSWORD_LENGTH = 12;
const MAX_PASSWORD_LENGTH = 1024;
const MAX_USERNAME_LENGTH = 64;
/** The sign-in throttle keeps its own keys under `<username>@address:`, so no account may. */
const RESERVED_IN_USERNAME = "@address:";

export const ROLE_LABELS: Record<Role, string> = { user: "User", admin: "Admin" };

export type FieldErrors = Partial<Record<"username" | "password" | "confirm", string>>;

export function validatePassword(password: string, confirm: string): FieldErrors {
  const errors: FieldErrors = {};
  if (password.length < MIN_PASSWORD_LENGTH)
    errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  else if (password.length > MAX_PASSWORD_LENGTH)
    errors.password = `Use at most ${MAX_PASSWORD_LENGTH} characters.`;
  if (confirm !== password) errors.confirm = "The passwords don't match.";
  return errors;
}

export function validateNewUser(values: {
  username: string;
  password: string;
  confirm: string;
}): FieldErrors {
  const errors: FieldErrors = validatePassword(values.password, values.confirm);
  const username = values.username.trim();
  if (!username) errors.username = "Choose a username.";
  else if (username.length > MAX_USERNAME_LENGTH)
    errors.username = `Use at most ${MAX_USERNAME_LENGTH} characters.`;
  else if (/\s/.test(username)) errors.username = "No spaces, please.";
  else if (username.toLowerCase().includes(RESERVED_IN_USERNAME))
    errors.username = `A username can't contain "${RESERVED_IN_USERNAME}".`;
  return errors;
}

/** One sentence a person can act on, for any failure of the users API. */
export function explainUserError(error: unknown): string {
  if (!(error instanceof HttpError)) {
    return "Can't reach the server. Check your connection and try again.";
  }
  switch (error.code) {
    case "username_taken":
      return "Another account already has that username. Pick another one.";
    case "invalid_username":
      return "That username isn't accepted: no spaces or control characters.";
    case "last_operator":
      return "This is the last enabled admin. Make another admin first, or the instance would have nobody to manage accounts.";
    case "unknown_account":
      return "That account no longer exists. The list has been refreshed.";
    case "forbidden":
      return "Only an admin can manage user accounts.";
  }
  if (error.status === 401) return "Your session ended. Sign in again to manage users.";
  if (error.status === 422) return explainInvalidRequest(error);
  return `Something went wrong (${error.status}). Try again.`;
}

/** A 422 without a domain code: name the field the server refused, with its reason. */
function explainInvalidRequest(error: HttpError): string {
  const [first] = error.fields;
  const field = first?.loc.at(-1);
  if (first && (field === "username" || field === "password")) {
    return `That ${field} isn't accepted: ${first.msg}.`;
  }
  if (first) return `The server refused ${String(field)}: ${first.msg}.`;
  return `The server refused the request: ${error.message}.`;
}
