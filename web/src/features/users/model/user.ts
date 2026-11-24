import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import { messages } from "../messages";

export type User = components["schemas"]["UserSummary"];
export type NewUser = components["schemas"]["CreateUserCommand"];
export type Role = NonNullable<NewUser["role"]>;

// Mirrors the backend's rules (identity/constants.py); the server stays the authority.
export const MIN_PASSWORD_LENGTH = 12;
const MAX_PASSWORD_LENGTH = 1024;
const MAX_USERNAME_LENGTH = 64;
/** The sign-in throttle keeps its own keys under `<username>@address:`, so no account may. */
const RESERVED_IN_USERNAME = "@address:";

/** The roles the create form offers, in its order; their names are in the catalogue. */
export const ROLES: readonly Role[] = ["user", "admin"];

export type FieldErrors = Partial<Record<"username" | "password" | "confirm", string>>;

export function validatePassword(
  password: string,
  confirm: string,
  language: Language = currentLanguage(),
): FieldErrors {
  const t = messages[language].validation;
  const errors: FieldErrors = {};
  if (password.length < MIN_PASSWORD_LENGTH)
    errors.password = t.passwordTooShort(MIN_PASSWORD_LENGTH);
  else if (password.length > MAX_PASSWORD_LENGTH) errors.password = t.tooLong(MAX_PASSWORD_LENGTH);
  if (confirm !== password) errors.confirm = t.mismatch;
  return errors;
}

export function validateNewUser(
  values: {
    username: string;
    password: string;
    confirm: string;
  },
  language: Language = currentLanguage(),
): FieldErrors {
  const t = messages[language].validation;
  const errors: FieldErrors = validatePassword(values.password, values.confirm, language);
  const username = values.username.trim();
  if (!username) errors.username = t.usernameMissing;
  else if (username.length > MAX_USERNAME_LENGTH) errors.username = t.tooLong(MAX_USERNAME_LENGTH);
  else if (/\s/.test(username)) errors.username = t.noSpaces;
  else if (username.toLowerCase().includes(RESERVED_IN_USERNAME))
    errors.username = t.reserved(RESERVED_IN_USERNAME);
  return errors;
}

/** One sentence a person can act on, for any failure of the users API. */
export function explainUserError(error: unknown, language: Language = currentLanguage()): string {
  const t = messages[language].errors;
  if (!(error instanceof HttpError)) return t.offline;
  switch (error.code) {
    case "username_taken":
      return t.usernameTaken;
    case "invalid_username":
      return t.invalidUsername;
    case "last_operator":
      return t.lastOperator;
    case "unknown_account":
      return t.unknownAccount;
    case "external_account":
      return t.externalAccount;
    case "forbidden":
      return t.forbidden;
  }
  if (error.status === 401) return t.sessionEnded;
  if (error.status === 422) return explainInvalidRequest(error, language);
  return t.other(error.status);
}

/** A 422 without a domain code: name the field the server refused, with its reason. */
function explainInvalidRequest(error: HttpError, language: Language): string {
  const t = messages[language].errors;
  const [first] = error.fields;
  const field = first?.loc.at(-1);
  if (first && (field === "username" || field === "password")) {
    return t.fieldRefused(field, first.msg);
  }
  if (first) return t.otherFieldRefused(String(field), first.msg);
  return t.requestRefused(error.message);
}
