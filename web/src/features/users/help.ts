import { Ellipsis, ListChecks, Plus, ShieldCheck, Users } from "lucide-react";
import type { HelpTopic } from "@/shared/ui/page-help";

/** The users page's tour. Targets are the `data-tour` values in users-page.tsx and users-views.tsx. */
export const usersHelp: HelpTopic = {
  title: { en: "Managing people", pl: "Zarządzanie osobami" },
  steps: [
    {
      icon: ListChecks,
      target: "users-views",
      title: { en: "Three views", pl: "Trzy widoki" },
      body: {
        en: "The accounts, every account's API tokens, and the role rules that give roles by group or team.",
        pl: "Konta, tokeny API wszystkich kont i reguły ról, które nadają role według grupy lub zespołu.",
      },
      guide: "getting-started/accounts/",
    },
    {
      icon: Plus,
      target: "users-new",
      title: { en: "Add a local account", pl: "Nowe konto lokalne" },
      body: {
        en: "Creates an account with a username and password. People who sign in through a provider get one on their first sign-in.",
        pl: "Tworzy konto z nazwą użytkownika i hasłem. Osoby logujące się przez dostawcę dostają konto przy pierwszym logowaniu.",
      },
      guide: "getting-started/accounts/#local-user-accounts",
    },
    {
      icon: Users,
      target: "users-table",
      title: { en: "Accounts", pl: "Konta" },
      body: {
        en: "Each account's role, how it signs in, its groups and the roles rules give it.",
        pl: "Rola każdego konta, sposób logowania, jego grupy i role nadane przez reguły.",
      },
      guide: "getting-started/accounts/#groups-and-role",
    },
    {
      icon: Ellipsis,
      target: "users-table",
      title: { en: "Row actions", pl: "Akcje wiersza" },
      body: {
        en: "Reset a password, disable or enable an account, or see its API tokens and access-log entries.",
        pl: "Zresetuj hasło, wyłącz lub włącz konto albo zobacz jego tokeny API i wpisy w dzienniku dostępu.",
      },
      guide: "getting-started/accounts/#sessions-and-lost-passwords",
    },
  ],
};

/** The role rules page's tour. Targets are the `data-tour` values in role-rules-page.tsx. */
export const roleRulesHelp: HelpTopic = {
  title: { en: "Role rules", pl: "Reguły ról" },
  steps: [
    {
      icon: ListChecks,
      target: "rules-list",
      title: { en: "The rules", pl: "Reguły" },
      body: {
        en: "Who gets which role: members of a group, a role value, a GitHub organization or team at a provider. Rules from the configuration file are read-only.",
        pl: "Kto dostaje jaką rolę: członkowie grupy, wartości roli, organizacji lub zespołu GitHub u dostawcy. Reguł z pliku konfiguracji nie da się tu zmienić.",
      },
      guide: "configuration/sign-in/role-rules/",
    },
    {
      icon: Plus,
      target: "rules-add",
      title: { en: "Add a rule", pl: "Nowa reguła" },
      body: {
        en: "Pick the provider and the membership, then the role: instance admin, library creation, or a role on every library or chosen ones.",
        pl: "Wybierz dostawcę i członkostwo, potem rolę: administrator instancji, tworzenie bibliotek albo rola we wszystkich lub wybranych bibliotekach.",
      },
      guide: "configuration/sign-in/role-rules/",
    },
    {
      icon: ShieldCheck,
      target: "rules-list",
      title: { en: "Rules only add", pl: "Reguły tylko dodają" },
      body: {
        en: "A rule never takes a role away; the highest role counts. Every library leaves out private libraries.",
        pl: "Reguła nigdy nie odbiera roli; liczy się najwyższa. „Wszystkie biblioteki” pomija biblioteki prywatne.",
      },
      guide: "configuration/sign-in/role-rules/",
    },
  ],
};
