import { defineMessages, plural } from "@/shared/lib/i18n";

/** The role rules view's strings: the list, the add form, removal, errors. */
export const rulesMessages = defineMessages(
  {
    page: {
      documentTitle: "Role rules",
      description:
        "Who gets which role from their memberships at a sign-in provider: a group, a role value, a GitHub organization or team. A rule only adds to the roles people were given directly; the highest counts.",
      add: "Add rule",
      count: (n: number) => plural.en(n, { one: "# rule", other: "# rules" }),
      noProviders: "No sign-in provider is configured, so no rule can match anyone yet.",
      configuredOnly: (names: string) =>
        `${names} takes only the configuration file's rules (configured_rules_only).`,
    },
    list: {
      label: "Role rules",
      columns: {
        source: "Members of",
        grant: "Get",
        provider: "Provider",
        by: "Added by",
        actions: "Actions",
      },
      configured: "Configuration file",
      configuredHint: "Set in the configuration file; change it there.",
      anyProvider: "Any provider",
      remove: (rule: string) => `Remove rule ${rule}`,
      emptyTitle: "No rules yet",
      emptyBody:
        "Add a rule to give a team, a group or a role value a role on every library, or the admin role, without sharing person by person.",
      loadFailed: "Couldn't load the role rules.",
    },
    add: {
      title: "Add a role rule",
      description:
        "Everyone the provider puts in this membership gets the role. Library roles apply at once; the admin role at once for accounts seen before, and at each next sign-in.",
      provider: "Provider",
      source: "Members of",
      sources: {
        github_team: "GitHub team",
        github_org: "GitHub organization",
        group: "Group",
        role: "Role value",
      },
      value: "Name",
      valueHints: {
        github_team: "org/team-slug, for example acme/docs-writers",
        github_org: "The organization's login, for example acme",
        group: "As the provider names it, without the group prefix",
        role: "A value of the provider's role claim, for example ExactDocs.Reader",
      },
      grant: "Get",
      grants: {
        viewer: "Viewer",
        contributor: "Contributor",
        admin: "Library admin",
        create_libraries: "May create libraries",
        instance_admin: "Instance admin",
      },
      scope: "On",
      everyLibrary: "Every library (private ones excepted)",
      chosen: "Chosen libraries",
      libraries: "Libraries",
      librariesHint: "A rule reaches a private library only when it names it.",
      valueMissing: "Name the membership.",
      librariesMissing: "Choose at least one library.",
      submit: "Add rule",
      added: (rule: string) => `Rule added: ${rule}`,
    },
    remove: {
      title: "Remove this rule?",
      description: (rule: string) =>
        `${rule}. What it gave ends at the next request; roles given directly stay.`,
      removed: (rule: string) => `Rule removed: ${rule}`,
    },
    /** Where a role comes from, on the users list. */
    origin: {
      fromRule: "From a rule",
      rules: "Rules",
      direct: "Given directly",
      more: (n: number, name: string) =>
        `${plural.en(n, { one: "# more rule", other: "# more rules" })} of ${name}`,
      all: (name: string) => `Rules that match ${name}`,
    },
    errors: {
      offline: "Can't reach the server. Check your connection and try again.",
      sessionEnded: "Your session ended. Sign in again to manage role rules.",
      forbidden: "Only the server's operators manage role rules.",
      exists: "This provider already has that rule.",
      configuredOnly: "This provider takes only the configuration file's rules.",
      configured: "This rule is set in the configuration file; change it there.",
      lastOperator:
        "Removing this rule would leave no enabled admin. Make someone else an admin first.",
      gone: "The rule or its provider is gone. Reload the page.",
      invalid: (why: string) => `The server refused the rule: ${why}`,
      other: (status: number) => `Something went wrong (${status}). Try again.`,
    },
  },
  {
    page: {
      documentTitle: "Reguły ról",
      description:
        "Kto dostaje jaką rolę dzięki członkostwu u dostawcy logowania: w grupie, z wartością roli, w organizacji lub zespole GitHub. Reguła tylko dodaje do ról nadanych bezpośrednio; liczy się najwyższa.",
      add: "Dodaj regułę",
      count: (n) => plural.pl(n, { one: "# reguła", few: "# reguły", many: "# reguł" }),
      noProviders:
        "Nie skonfigurowano żadnego dostawcy logowania, więc żadna reguła nikogo jeszcze nie obejmuje.",
      configuredOnly: (names) =>
        `${names} przyjmuje tylko reguły z pliku konfiguracyjnego (configured_rules_only).`,
    },
    list: {
      label: "Reguły ról",
      columns: {
        source: "Członkowie",
        grant: "Dostają",
        provider: "Dostawca",
        by: "Dodał",
        actions: "Akcje",
      },
      configured: "Plik konfiguracyjny",
      configuredHint: "Ustawiona w pliku konfiguracyjnym; zmień ją tam.",
      anyProvider: "Każdy dostawca",
      remove: (rule) => `Usuń regułę ${rule}`,
      emptyTitle: "Nie ma jeszcze reguł",
      emptyBody:
        "Dodaj regułę, aby dać zespołowi, grupie lub wartości roli rolę we wszystkich bibliotekach albo rolę administratora, bez udostępniania każdej osobie z osobna.",
      loadFailed: "Nie udało się wczytać reguł ról.",
    },
    add: {
      title: "Dodaj regułę ról",
      description:
        "Każdy, kogo dostawca zalicza do tego członkostwa, dostaje rolę. Role w bibliotekach działają od razu; rola administratora od razu dla znanych kont i przy każdym kolejnym logowaniu.",
      provider: "Dostawca",
      source: "Członkowie",
      sources: {
        github_team: "Zespół GitHub",
        github_org: "Organizacja GitHub",
        group: "Grupa",
        role: "Wartość roli",
      },
      value: "Nazwa",
      valueHints: {
        github_team: "organizacja/zespół, na przykład acme/docs-writers",
        github_org: "Login organizacji, na przykład acme",
        group: "Tak, jak nazywa ją dostawca, bez prefiksu grup",
        role: "Wartość roszczenia ról dostawcy, na przykład ExactDocs.Reader",
      },
      grant: "Dostają",
      grants: {
        viewer: "Czytelnik",
        contributor: "Współtwórca",
        admin: "Administrator biblioteki",
        create_libraries: "Mogą tworzyć biblioteki",
        instance_admin: "Administrator instancji",
      },
      scope: "W",
      everyLibrary: "Wszystkich bibliotekach (poza prywatnymi)",
      chosen: "Wybranych bibliotekach",
      libraries: "Biblioteki",
      librariesHint: "Reguła obejmuje prywatną bibliotekę tylko wtedy, gdy ją wymienia.",
      valueMissing: "Podaj nazwę członkostwa.",
      librariesMissing: "Wybierz co najmniej jedną bibliotekę.",
      submit: "Dodaj regułę",
      added: (rule) => `Dodano regułę: ${rule}`,
    },
    remove: {
      title: "Usunąć tę regułę?",
      description: (rule) =>
        `${rule}. To, co dawała, kończy się przy następnym żądaniu; role nadane bezpośrednio zostają.`,
      removed: (rule) => `Usunięto regułę: ${rule}`,
    },
    origin: {
      fromRule: "Z reguły",
      rules: "Reguły",
      direct: "Nadana bezpośrednio",
      more: (n, name) =>
        `${plural.pl(n, { one: "Jeszcze # reguła", few: "Jeszcze # reguły", many: "Jeszcze # reguł" })} użytkownika ${name}`,
      all: (name) => `Reguły obejmujące użytkownika ${name}`,
    },
    errors: {
      offline: "Nie można połączyć się z serwerem. Sprawdź połączenie i spróbuj ponownie.",
      sessionEnded: "Sesja wygasła. Zaloguj się ponownie, aby zarządzać regułami ról.",
      forbidden: "Regułami ról zarządzają tylko operatorzy serwera.",
      exists: "Ten dostawca ma już taką regułę.",
      configuredOnly: "Ten dostawca przyjmuje tylko reguły z pliku konfiguracyjnego.",
      configured: "Ta reguła jest ustawiona w pliku konfiguracyjnym; zmień ją tam.",
      lastOperator:
        "Usunięcie tej reguły nie zostawiłoby żadnego aktywnego administratora. Najpierw nadaj komuś rolę administratora.",
      gone: "Reguła lub jej dostawca już nie istnieje. Odśwież stronę.",
      invalid: (why) => `Serwer odrzucił regułę: ${why}`,
      other: (status) => `Coś poszło nie tak (${status}). Spróbuj ponownie.`,
    },
  },
);
