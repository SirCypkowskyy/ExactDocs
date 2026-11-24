import { queryOptions } from "@tanstack/react-query";
import type { components } from "./api-schema";
import { getJson } from "./http";
import { defineMessages } from "./i18n";
import { AI_KEY } from "./query-keys";

export type AiProvider = components["schemas"]["ProviderOut"];
type ProviderList = components["schemas"]["ProviderListOut"];
export type AiRole = components["schemas"]["RoleOut"];
type RoleList = components["schemas"]["RoleListOut"];

type ModelRole = components["schemas"]["ModelRole"];
export type ThinkingLevel = components["schemas"]["ThinkingLevel"];

/**
 * The words for model roles and thinking levels, as people read them:
 * `const ai = useMessages(aiLabels)`, then `ai.roles[role]`, `ai.thinking[level]`, `ai.thinkingHint`.
 */
export const aiLabels = defineMessages(
  {
    roles: {
      embedding: "Embedding",
      reranker: "Reranker",
      llm: "LLM",
      judge: "Judge",
    } satisfies Record<ModelRole, string>,
    thinking: {
      minimal: "Minimal",
      low: "Low",
      medium: "Medium",
      high: "High",
      xhigh: "Extra high",
    } satisfies Record<ThinkingLevel, string>,
    /** What a thinking level costs, said where it is chosen. */
    thinkingHint:
      "How much the model thinks before it answers. Thinking tokens are billed as output, and several providers default to a high level: HyDE, the judge and agentic search rarely need more than Low.",
  },
  {
    roles: {
      embedding: "Embedding",
      reranker: "Reranker",
      llm: "LLM",
      judge: "Sędzia",
    },
    thinking: {
      minimal: "Minimalny",
      low: "Niski",
      medium: "Średni",
      high: "Wysoki",
      xhigh: "Bardzo wysoki",
    },
    thinkingHint:
      "Ile model myśli, zanim odpowie. Tokeny myślenia są rozliczane jak tokeny wyjściowe, a kilku dostawców domyślnie ustawia wysoki poziom: HyDE, sędzia i wyszukiwanie agentowe rzadko potrzebują więcej niż Niski.",
  },
);

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

/** The thinking levels of the `llm` and `judge` roles, least first (#421). */
export const THINKING_LEVELS: readonly ThinkingLevel[] = [
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
];

/** The instance's model roles (`embedding`, `reranker`, `llm`, `judge`), as configured. */
export const aiRolesQueryOptions = () =>
  queryOptions({
    queryKey: [...AI_KEY, "roles"] as const,
    queryFn: async ({ signal }) => (await getJson<RoleList>("/v1/ai/roles", { signal })).roles,
  });
