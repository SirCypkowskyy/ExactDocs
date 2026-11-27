import { queryOptions } from "@tanstack/react-query";
import type { components } from "@/shared/lib/api-schema";
import { getJson, type QueryOf, sendJson } from "@/shared/lib/http";
import type { LibraryChoices } from "@/shared/ui/library-combobox";
import type { NewRoleRule, RoleRule, RoleRuleList } from "../model/role-rule";

const roleRulesKey = ["role-rules"] as const;

/**
 * What a rule change makes stale: the rules, the accounts' rules, every library's sharing page
 * ("From role rules") and the access log. The other slices' keys are named by prefix only.
 */
export const RULE_CHANGE_KEYS = [roleRulesKey, ["users"], ["sharing"], ["access-log"]] as const;

/** Every role rule, the configuration file's first, and the providers rules can name. */
export const roleRulesQueryOptions = () =>
  queryOptions({
    queryKey: roleRulesKey,
    queryFn: ({ signal }) => getJson<RoleRuleList>("/v1/role-rules", { signal }),
  });

export const addRoleRule = (rule: NewRoleRule) =>
  sendJson<RoleRule>("POST", "/v1/role-rules", rule);

export const removeRoleRule = (id: string) =>
  sendJson<undefined>("DELETE", `/v1/role-rules/${encodeURIComponent(id)}`);

/** The libraries a rule can be limited to, by ID; the API's largest page per request. */
export const ruleLibrariesQueryOptions = (q: string) =>
  queryOptions({
    queryKey: [...roleRulesKey, "libraries", q] as const,
    queryFn: ({ signal }): Promise<LibraryChoices> => {
      const query = {
        limit: 200,
        sort: "id",
        ...(q && { q }),
      } satisfies QueryOf<"/api/v1/libraries">;
      return getJson<components["schemas"]["LibraryList"]>("/v1/libraries", {
        signal,
        query,
      }).then((list) => ({
        options: list.libraries.map((l) => ({ id: l.id, title: l.title, logo: l.logo })),
        total: list.total,
      }));
    },
  });
