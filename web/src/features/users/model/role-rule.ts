import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language } from "@/shared/lib/i18n";
import type { RoleRule } from "@/shared/lib/role-rules";
import { rulesMessages } from "../rules-messages";

export type { RoleRule };
export type RoleRuleList = components["schemas"]["RoleRuleList"];
export type RuleProvider = components["schemas"]["RuleProviderSummary"];
export type NewRoleRule = components["schemas"]["RoleRuleRequest"];
export type RuleSource = NewRoleRule["source"];
export type RuleGrant = NewRoleRule["grant"];

/** The grants the form offers, in its order. */
export const GRANTS: readonly RuleGrant[] = [
  "viewer",
  "contributor",
  "admin",
  "create_libraries",
  "instance_admin",
];

/** A library role, which may be limited to chosen libraries; the others are instance-wide. */
export const isLibraryGrant = (grant: RuleGrant) =>
  grant === "viewer" || grant === "contributor" || grant === "admin";

/** The sources a provider's rules can name: GitHub names on GitHub, role values with a claim. */
export function sourcesOf(provider: RuleProvider | undefined): RuleSource[] {
  if (!provider) return [];
  if (provider.github) return ["github_team", "github_org", "group"];
  return provider.role_claim ? ["group", "role"] : ["group"];
}

/** The providers a rule can be added for: those that take more than the configuration file's. */
export const editableProviders = (list: RoleRuleList | undefined) =>
  (list?.providers ?? []).filter((p) => !p.configured_rules_only);

/** The rules that match an account, by the IDs the users list gives it. */
export function rulesOf(ids: readonly string[], list: RoleRuleList | undefined): RoleRule[] {
  const byId = new Map((list?.rules ?? []).map((rule) => [rule.id, rule]));
  return ids.flatMap((id) => byId.get(id) ?? []);
}

/** One sentence a person can act on, for any failure of the role rules API. */
export function explainRuleError(error: unknown, language: Language = currentLanguage()): string {
  const t = rulesMessages[language].errors;
  if (!(error instanceof HttpError)) return t.offline;
  switch (error.code) {
    case "role_rule_exists":
      return t.exists;
    case "rules_configured_only":
      return t.configuredOnly;
    case "configured_rule":
      return t.configured;
    case "last_operator":
      return t.lastOperator;
    case "unknown_provider":
    case "unknown_role_rule":
      return t.gone;
    case "invalid_role_rule":
      return t.invalid(error.message);
    case "forbidden":
      return t.forbidden;
  }
  if (error.status === 401) return t.sessionEnded;
  if (error.status === 422) return t.invalid(error.fields[0]?.msg ?? error.message);
  return t.other(error.status);
}
