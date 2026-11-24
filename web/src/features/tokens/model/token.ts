import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import { messages } from "../messages";

export type Token = components["schemas"]["TokenSummary"];
export type TokenGrant = components["schemas"]["TokenGrant"];

/** An account holds at most this many tokens (backend: 409 `too_many_tokens`). */
export const MAX_TOKENS = 50;
/** `CreateTokenCommand.name` maxLength in openapi.json. */
export const MAX_NAME_LENGTH = 256;

/** The expiry choices, in the order the form offers them; their words are in the catalogue. */
export const EXPIRY_CHOICES = ["never", "7", "30", "90", "365"] as const;
export type ExpiryChoice = (typeof EXPIRY_CHOICES)[number];

/** The `expires_at` to send (UTC, in the future), or nothing for a token that never expires. */
export function expiresAt(choice: ExpiryChoice, now = Date.now()): string | undefined {
  return choice === "never" ? undefined : new Date(now + Number(choice) * 86_400_000).toISOString();
}

export function explainTokenError(error: unknown, language: Language = currentLanguage()): string {
  const t = messages[language].errors;
  if (!(error instanceof HttpError)) return t.offline;
  if (error.code === "too_many_tokens") return t.tooMany(MAX_TOKENS);
  if (error.status === 401) return t.sessionEnded;
  if (error.status === 422) return t.invalid;
  return t.other(error.status);
}

/** The session cookie is gone: nothing here can work until the user signs in again. */
export const isSessionEnded = (error: unknown) =>
  error instanceof HttpError && error.status === 401;

/** Revoking a token that is already gone (another tab, a password reset) is the goal reached. */
export const isAlreadyGone = (error: unknown) => error instanceof HttpError && error.status === 404;
