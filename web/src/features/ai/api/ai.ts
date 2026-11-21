import { queryOptions } from "@tanstack/react-query";
import type { AiRole, ThinkingLevel } from "@/shared/lib/ai-queries";
import { getJson, sendJson } from "@/shared/lib/http";
import { AI_KEY } from "@/shared/lib/query-keys";
import type { AiUsage, EmbeddingProgress, ModelChecks } from "../model/ai";

/** How far each embedding space has got. */
export const embeddingProgressQueryOptions = () =>
  queryOptions({
    queryKey: [...AI_KEY, "embedding"] as const,
    queryFn: ({ signal }) => getJson<EmbeddingProgress>("/v1/ai/embedding", { signal }),
  });

/** Spend today and this month, and the budget left, per scope. */
export const aiUsageQueryOptions = () =>
  queryOptions({
    queryKey: [...AI_KEY, "usage"] as const,
    queryFn: ({ signal }) => getJson<AiUsage>("/v1/ai/usage", { signal }),
  });

/** Set (or clear, with null) an instance role's thinking level; `llm` and `judge` only. */
export const setRoleThinking = (role: "llm" | "judge", thinking: ThinkingLevel | null) =>
  sendJson<AiRole>("PUT", `/v1/ai/roles/${role}`, { thinking });

/** One minimal call per role that uses the profile; a failed call is a check, not an error. */
export const checkProvider = (name: string) =>
  sendJson<ModelChecks>("POST", `/v1/ai/providers/${encodeURIComponent(name)}/check`);
