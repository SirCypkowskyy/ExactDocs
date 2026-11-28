import type { components } from "./api-schema";
import { currentLanguage, defineMessages, type Language } from "./i18n";

/*
 * A role rule (#577) in words, the same on the users page, a library's sharing page and the
 * access log: "GitHub team acme/docs-writers → contributor on every library".
 */

export type RoleRule = components["schemas"]["RoleRuleSummary"];

const messages = defineMessages(
  {
    source: {
      github_org: "GitHub organization",
      github_team: "GitHub team",
      group: "group",
      role: "role",
      everyone: "every account",
    },
    grant: {
      instance_admin: "instance admin",
      create_libraries: "may create libraries",
      viewer: "viewer",
      contributor: "contributor",
      admin: "admin",
    },
    everyLibrary: " on every library",
    onLibraries: (ids: string) => ` on ${ids}`,
  },
  {
    source: {
      github_org: "organizacja GitHub",
      github_team: "zespół GitHub",
      group: "grupa",
      role: "rola",
      everyone: "każde konto",
    },
    grant: {
      instance_admin: "administrator instancji",
      create_libraries: "może tworzyć biblioteki",
      viewer: "czytelnik",
      contributor: "współtwórca",
      admin: "administrator",
    },
    everyLibrary: " we wszystkich bibliotekach",
    onLibraries: (ids) => ` w ${ids}`,
  },
);

/** Who a rule matches: "GitHub team acme/docs-writers", or "every account" (the default role). */
export function ruleSource(rule: RoleRule, language: Language = currentLanguage()): string {
  const source = messages[language].source[rule.source];
  return rule.source === "everyone" ? source : `${source} ${rule.value}`;
}

/** What a rule gives: "contributor on every library", "instance admin". */
export function ruleGrant(rule: RoleRule, language: Language = currentLanguage()): string {
  const t = messages[language];
  const grant = t.grant[rule.grant];
  if (rule.grant === "instance_admin" || rule.grant === "create_libraries") return grant;
  return `${grant}${rule.libraries ? t.onLibraries(rule.libraries.join(", ")) : t.everyLibrary}`;
}

/** A rule as one phrase: "GitHub team acme/docs-writers → contributor on every library". */
export function ruleText(rule: RoleRule, language: Language = currentLanguage()): string {
  return `${ruleSource(rule, language)} → ${ruleGrant(rule, language)}`;
}
