import { queryOptions } from "@tanstack/react-query";
import { type ApiPath, getJson } from "@/shared/lib/http";
import { AI_KEY } from "@/shared/lib/query-keys";
import type { AiUsage, Health } from "../model/notices";

/*
 * What the banner polls. Once a minute while the tab is visible: TanStack Query stops the interval
 * in a hidden tab (`refetchIntervalInBackground: false`) and catches up when it is shown again.
 */

/** How often the banner asks again. */
export const POLL_MS = 60_000;

const polling = {
  refetchInterval: POLL_MS,
  refetchIntervalInBackground: false,
  staleTime: POLL_MS / 2,
} as const;

/**
 * `GET /api/health` (the alias of `/healthz` under `/api`, so the dev server's proxy reaches it).
 * The probe lives outside `/api/v1`, so it is not in the generated schema: hence the cast.
 */
export const healthQueryOptions = () =>
  queryOptions({
    queryKey: ["instance", "health"] as const,
    queryFn: ({ signal }) => getJson<Health>("/health" as ApiPath, { signal }),
    ...polling,
  });

/** Spend and budgets per scope; the same query (and cache entry) the AI page and Overview read. */
export const aiUsageQueryOptions = () =>
  queryOptions({
    queryKey: [...AI_KEY, "usage"] as const,
    queryFn: ({ signal }) => getJson<AiUsage>("/v1/ai/usage", { signal }),
    ...polling,
  });
