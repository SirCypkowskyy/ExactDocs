import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import { isBrandIcon } from "@/shared/ui/brand-marks";
import { messages } from "../messages";
import type { SignInProvider } from "./session";

export type AccountProviders = components["schemas"]["AccountProviders"];
export type AccountProvider = components["schemas"]["AccountProvider"];
export type LinkStart = components["schemas"]["AccountLinkStart"];
export type UsageSettings = components["schemas"]["UsageSettingsOut"];

/** The sign-in page's order: the brands the UI has a mark for first, then the rest, each as configured. */
export function brandsFirst(providers: readonly SignInProvider[]): SignInProvider[] {
  const brands = providers.filter((p) => isBrandIcon(p.icon));
  return [...brands, ...providers.filter((p) => !isBrandIcon(p.icon))];
}

/** The codes a link can come back refused with (`?link_error=`), each with its own wording. */
const LINK_ERRORS = [
  "identity_linked_elsewhere",
  "provider_linked",
  "not_allowed",
  "not_linked",
  "sign_in_failed",
  "sign_in_cancelled",
  "unauthenticated",
  "provider_unavailable",
] as const;
type LinkErrorCode = (typeof LINK_ERRORS)[number];

export interface LinkProblem {
  message: string;
  link?: { href: string; label: string };
}

/**
 * Why a link came back refused (`/account?tab=sign-in&link_error=<code>`). The query string is not
 * trusted to say anything: a known code gets its own sentence, anything else the general one.
 */
export function explainLinkError(
  code: string | undefined,
  language: Language = currentLanguage(),
): LinkProblem | undefined {
  if (!code) return undefined;
  const t = messages[language].providers.linkErrors;
  const known = (LINK_ERRORS as readonly string[]).includes(code) ? (code as LinkErrorCode) : null;
  switch (known) {
    case "identity_linked_elsewhere":
      return { message: t.elsewhere };
    case "provider_linked":
      return { message: t.alreadyLinked };
    case "not_allowed":
      return { message: t.notAllowed };
    case "not_linked":
      return { message: t.notLinked };
    case "sign_in_cancelled":
      return { message: t.cancelled };
    case "unauthenticated":
      return { message: t.sessionEnded, link: { href: "/sign-in", label: t.signIn } };
    case "provider_unavailable":
      return { message: t.unavailable };
    default:
      return { message: t.failed };
  }
}

/** A failed Link or Unlink request, in words a person can act on. */
export function explainProviderError(
  error: unknown,
  name: string,
  language: Language = currentLanguage(),
): LinkProblem {
  const t = messages[language].providers.errors;
  if (!(error instanceof HttpError)) return { message: t.unreachable };
  switch (error.code) {
    case "provider_linked":
      return { message: t.alreadyLinked(name) };
    case "unknown_provider":
      return { message: t.unknown(name) };
    case "provider_unavailable":
      return { message: t.unavailable(name) };
    case "provider_not_linked":
      return { message: t.notLinked(name) };
    case "last_sign_in_method":
      return { message: t.lastMethod(name) };
    default:
      if (error.status === 401) {
        return { message: t.sessionEnded, link: { href: "/sign-in", label: t.signIn } };
      }
      return { message: t.server(error.status) };
  }
}

/** The provider `?linked=` names, if it is one of the account's: the parameter is not trusted. */
export function linkedProvider(
  name: string | undefined,
  providers: readonly { name: string; display_name: string }[],
): { name: string; display_name: string } | undefined {
  if (!name) return undefined;
  return providers.find((p) => p.name === name);
}
