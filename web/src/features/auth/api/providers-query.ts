import { queryOptions } from "@tanstack/react-query";
import { getJson, sendJson } from "@/shared/lib/http";
import type { AccountProviders, LinkStart, UsageSettings } from "../model/providers";

/*
 * Account → Sign-in → Linked sign-in providers (#506) and the people leaderboard switch (#510).
 * Every `/account/providers` call needs the session cookie (an API token is 401).
 */

export const accountProvidersQueryOptions = () =>
  queryOptions({
    queryKey: ["account", "providers"] as const,
    queryFn: ({ signal }) => getJson<AccountProviders>("/v1/account/providers", { signal }),
  });

/** Where a link started on the Sign-in tab comes back to (with `?linked=` or `?link_error=`). */
const LINK_RETURN_TO = "/account?tab=sign-in";

/**
 * Starts linking an identity of `provider`: the server sets the binding cookie and answers where
 * the browser goes next (the provider's sign-in).
 */
export function startLink(provider: string) {
  return sendJson<LinkStart>("POST", `/v1/account/providers/${encodeURIComponent(provider)}/link`, {
    return_to: LINK_RETURN_TO,
  });
}

/** Unlinks the account's identity of `provider`; answers the list as it is now. */
export function unlink(provider: string) {
  return sendJson<AccountProviders>(
    "DELETE",
    `/v1/account/providers/${encodeURIComponent(provider)}`,
  );
}

/** The operator's usage settings: whether the people leaderboard is on. Any caller may ask. */
export const usageSettingsQueryOptions = () =>
  queryOptions({
    queryKey: ["stats", "settings"] as const,
    queryFn: ({ signal }) => getJson<UsageSettings>("/v1/stats/settings", { signal }),
    staleTime: 5 * 60_000,
  });

/**
 * A full navigation away from the app (to the identity provider). One object so a test can watch
 * it without a browser that really leaves.
 */
export const browser = {
  leaveFor(url: string) {
    window.location.assign(url);
  },
};
