import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";

export type Token = components["schemas"]["TokenSummary"];
export type TokenGrant = components["schemas"]["TokenGrant"];

/** An account holds at most this many tokens (backend: 409 `too_many_tokens`). */
export const MAX_TOKENS = 50;
/** `CreateTokenCommand.name` maxLength in openapi.json. */
export const MAX_NAME_LENGTH = 256;

export const EXPIRY_CHOICES = [
  { value: "never", label: "Never" },
  { value: "7", label: "In 7 days" },
  { value: "30", label: "In 30 days" },
  { value: "90", label: "In 90 days" },
  { value: "365", label: "In a year" },
] as const;
export type ExpiryChoice = (typeof EXPIRY_CHOICES)[number]["value"];

/** The `expires_at` to send (UTC, in the future), or nothing for a token that never expires. */
export function expiresAt(choice: ExpiryChoice, now = Date.now()): string | undefined {
  return choice === "never" ? undefined : new Date(now + Number(choice) * 86_400_000).toISOString();
}

export const isExpired = (t: Token, now = Date.now()) =>
  t.expires_at !== null && Date.parse(t.expires_at) <= now;

export function explainTokenError(error: unknown): string {
  if (!(error instanceof HttpError)) {
    return "Can't reach the server. Check your connection and try again.";
  }
  if (error.code === "too_many_tokens") {
    return `You have ${MAX_TOKENS} tokens, the most an account can hold. Revoke one you no longer use first.`;
  }
  if (error.status === 401) return "Your session ended. Sign in again to manage tokens.";
  if (error.status === 422) return "That name or expiry isn't accepted. Check them and try again.";
  return `Something went wrong (${error.status}). Try again.`;
}
