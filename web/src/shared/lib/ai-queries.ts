import { queryOptions } from "@tanstack/react-query";
import type { components } from "./api-schema";
import { getJson } from "./http";
import { AI_KEY } from "./query-keys";

export type AiProvider = components["schemas"]["ProviderOut"];
type ProviderList = components["schemas"]["ProviderListOut"];
export type AiRole = components["schemas"]["RoleOut"];
type RoleList = components["schemas"]["RoleListOut"];

/** Each model role, as people read it. */
export const ROLE_LABEL: Record<components["schemas"]["ModelRole"], string> = {
  embedding: "Embedding",
  reranker: "Reranker",
  llm: "LLM",
  judge: "Judge",
};

/**
 * The AI provider profiles (admins). Keys and header values never come back: `key` only says
 * where a key comes from. The instance AI page and a library's overrides share this one query.
 */
export const aiProvidersQueryOptions = () =>
  queryOptions({
    queryKey: [...AI_KEY, "providers"] as const,
    queryFn: async ({ signal }) =>
      (await getJson<ProviderList>("/v1/ai/providers", { signal })).providers,
  });

export type ThinkingLevel = components["schemas"]["ThinkingLevel"];

/** The thinking levels of the `llm` and `judge` roles, least first (#421). */
export const THINKING_LEVELS: readonly ThinkingLevel[] = [
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
];

export const THINKING_LABEL: Record<ThinkingLevel, string> = {
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
};

/** What a thinking level costs, said where it is chosen. */
export const THINKING_HINT =
  "How much the model thinks before it answers. Thinking tokens are billed as output, and several providers default to a high level: HyDE, the judge and agentic search rarely need more than Low.";

/** The instance's model roles (`embedding`, `reranker`, `llm`, `judge`), as configured. */
export const aiRolesQueryOptions = () =>
  queryOptions({
    queryKey: [...AI_KEY, "roles"] as const,
    queryFn: async ({ signal }) => (await getJson<RoleList>("/v1/ai/roles", { signal })).roles,
  });
