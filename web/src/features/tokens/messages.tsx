import type { ReactNode } from "react";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";

/** The tokens slice's strings: the section, the list, the create dialog and the MCP config. */
export const messages = defineMessages(
  {
    section: {
      heading: "API tokens",
      description:
        "Connect an agent to ExactDocs without signing in. A token is shown once, when you create it.",
      newToken: "New token",
      limit: (max: number) =>
        `You have ${max} of ${max} tokens. Revoke one you no longer use to create another.`,
      loading: "Loading tokens",
      emptyTitle: "No tokens yet",
      createFirst: "Create your first token",
      emptyBody:
        "Create one, then give it to your agent as a bearer token. The config below shows where it goes.",
      /** `name` is missing when the revoked token is no longer the one in the dialog. */
      revoked: (name: string | undefined) => `${name ?? "Token"} revoked.`,
      revokedToast: (name: string | undefined) => `${name ?? "Token"} revoked`,
      created: (name: string) => `Token ${name} created.`,
      createdToast: (name: string) => `Token ${name} created`,
      confirmTitle: (name: string) => `Revoke “${name}”?`,
      /** `prefix` is the token's prefix in a code element, or nothing while the dialog closes. */
      confirmDescription: (prefix: ReactNode): ReactNode => (
        <>Anything using {prefix ?? "it"} stops working at once. This can't be undone.</>
      ),
      revoke: "Revoke",
    },
    list: {
      find: "Find a token",
      namePlaceholder: "Name",
      sortBy: "Sort by",
      sort: {
        newest: "Newest first",
        oldest: "Oldest first",
        nameAsc: "Name, A to Z",
        nameDesc: "Name, Z to A",
        recentlyUsed: "Recently used",
        expiry: "No expiry, then soonest",
      },
      noMatchTitle: "No tokens match",
      noMatch: (q: string) => `No token name contains “${q}”.`,
      label: "API tokens",
      allLibraries: "All libraries you can access",
      noLibraries: "No libraries",
      created: (date: string) => `Created ${date}`,
      expired: (date: string) => `Expired ${date}`,
      expires: (date: string) => `Expires ${date}`,
      noExpiry: "No expiry",
      lastUsed: (date: string) => `Last used ${date}`,
      neverUsed: "Never used",
      revokeNamed: (name: string) => `Revoke ${name}`,
      revoke: "Revoke",
      showing: (shown: number, total: number) => `Showing ${shown} of ${total}`,
      loadMore: "Load more",
    },
    create: {
      title: "New API token",
      description: (mcp: ReactNode) => <>Tokens let an agent read your documentation over {mcp}.</>,
      nameRequired: "Name the token after where it will run, like “laptop”.",
      signIn: "Sign in",
      name: "Name",
      namePlaceholder: "e.g. laptop",
      nameHint: "Only for you: it tells your tokens apart.",
      expires: "Expires",
      expiry: {
        never: "Never",
        "7": "In 7 days",
        "30": "In 30 days",
        "90": "In 90 days",
        "365": "In a year",
      },
      access: "Library access",
      accessHint:
        "Access always follows your current permissions. An empty selection allows no libraries.",
      allLibraries: "All libraries I can access",
      selectedLibraries: "Selected libraries",
      libraryIds: "Library IDs",
      submit: "Create token",
      revealTitle: "Copy your token now",
      revealWarning:
        "This is the only time you will see it. If you lose it, revoke it and create a new one.",
      tokenCopied: "Token copied",
      clickToSelect: "Click the token to select it.",
      copiedToClipboard: "Copied to the clipboard.",
      copyFailed: "Couldn't copy automatically. The token is selected: press Ctrl+C.",
      copyToken: "Copy token",
    },
    config: {
      heading: "Connect an agent",
      copied: "Config copied",
      copiedHint: "Replace exd_YOUR_TOKEN with your token.",
      copyFailed: "Couldn't copy. Select the config and press Ctrl+C.",
      copyConfig: "Copy config",
      description:
        "Paste this into your MCP client's config and put a token in place of the placeholder.",
      label: "MCP client config",
    },
    errors: {
      offline: "Can't reach the server. Check your connection and try again.",
      tooMany: (max: number) =>
        `You have ${max} tokens, the most an account can hold. Revoke one you no longer use first.`,
      sessionEnded: "Your session ended. Sign in again to manage tokens.",
      invalid: "That name or expiry isn't accepted. Check them and try again.",
      other: (status: number) => `Something went wrong (${status}). Try again.`,
    },
  },
  {
    section: {
      heading: "Tokeny API",
      description:
        "Połącz agenta z ExactDocs bez logowania. Token jest widoczny tylko raz, zaraz po utworzeniu.",
      newToken: "Nowy token",
      limit: (max) =>
        `Masz ${formatNumber(max, "pl")} z ${plural.pl(max, { one: "# tokenu", few: "# tokenów", many: "# tokenów" })}. Unieważnij token, którego już nie używasz, aby utworzyć kolejny.`,
      loading: "Wczytywanie tokenów",
      emptyTitle: "Nie ma jeszcze tokenów",
      createFirst: "Utwórz pierwszy token",
      emptyBody:
        "Utwórz token i przekaż go agentowi jako token typu bearer. Konfiguracja poniżej pokazuje, gdzie go wpisać.",
      revoked: (name) => (name ? `Unieważniono token ${name}.` : "Unieważniono token."),
      revokedToast: (name) => (name ? `Unieważniono token ${name}` : "Unieważniono token"),
      created: (name) => `Utworzono token ${name}.`,
      createdToast: (name) => `Utworzono token ${name}`,
      confirmTitle: (name) => `Unieważnić token „${name}”?`,
      confirmDescription: (prefix) =>
        prefix ? (
          <>Wszystko, co używa {prefix}, od razu przestanie działać. Tego nie można cofnąć.</>
        ) : (
          "Wszystko, co go używa, od razu przestanie działać. Tego nie można cofnąć."
        ),
      revoke: "Unieważnij",
    },
    list: {
      find: "Znajdź token",
      namePlaceholder: "Nazwa",
      sortBy: "Sortuj według",
      sort: {
        newest: "Od najnowszych",
        oldest: "Od najstarszych",
        nameAsc: "Nazwa, od A do Z",
        nameDesc: "Nazwa, od Z do A",
        recentlyUsed: "Ostatnio używane",
        expiry: "Bezterminowe, potem wygasające najwcześniej",
      },
      noMatchTitle: "Brak pasujących tokenów",
      noMatch: (q) => `Żadna nazwa tokenu nie zawiera „${q}”.`,
      label: "Tokeny API",
      allLibraries: "Wszystkie biblioteki, do których masz dostęp",
      noLibraries: "Brak bibliotek",
      created: (date) => `Utworzono ${date}`,
      expired: (date) => `Wygasł ${date}`,
      expires: (date) => `Wygasa ${date}`,
      noExpiry: "Bezterminowy",
      lastUsed: (date) => `Ostatnio użyty ${date}`,
      neverUsed: "Nigdy nieużywany",
      revokeNamed: (name) => `Unieważnij ${name}`,
      revoke: "Unieważnij",
      showing: (shown, total) =>
        `Wyświetlono ${formatNumber(shown, "pl")} z ${formatNumber(total, "pl")}`,
      loadMore: "Wczytaj więcej",
    },
    create: {
      title: "Nowy token API",
      description: (mcp) => <>Tokeny pozwalają agentowi czytać Twoją dokumentację przez {mcp}.</>,
      nameRequired: "Nazwij token od miejsca, w którym będzie używany, np. „laptop”.",
      signIn: "Zaloguj się",
      name: "Nazwa",
      namePlaceholder: "np. laptop",
      nameHint: "Widoczna tylko dla Ciebie: pozwala odróżnić Twoje tokeny.",
      expires: "Wygasa",
      expiry: {
        never: "Nigdy",
        "7": "Za 7 dni",
        "30": "Za 30 dni",
        "90": "Za 90 dni",
        "365": "Za rok",
      },
      access: "Dostęp do bibliotek",
      accessHint:
        "Dostęp zawsze wynika z Twoich bieżących uprawnień. Pusty wybór nie daje dostępu do żadnej biblioteki.",
      allLibraries: "Wszystkie biblioteki, do których mam dostęp",
      selectedLibraries: "Wybrane biblioteki",
      libraryIds: "Identyfikatory bibliotek",
      submit: "Utwórz token",
      revealTitle: "Skopiuj teraz swój token",
      revealWarning:
        "Widzisz go tylko ten jeden raz. Jeśli go zgubisz, unieważnij go i utwórz nowy.",
      tokenCopied: "Skopiowano token",
      clickToSelect: "Kliknij token, aby go zaznaczyć.",
      copiedToClipboard: "Skopiowano do schowka.",
      copyFailed: "Nie udało się skopiować automatycznie. Token jest zaznaczony: naciśnij Ctrl+C.",
      copyToken: "Kopiuj token",
    },
    config: {
      heading: "Połącz agenta",
      copied: "Skopiowano konfigurację",
      copiedHint: "Zastąp exd_YOUR_TOKEN swoim tokenem.",
      copyFailed: "Nie udało się skopiować. Zaznacz konfigurację i naciśnij Ctrl+C.",
      copyConfig: "Kopiuj konfigurację",
      description:
        "Wklej to do konfiguracji swojego klienta MCP i wstaw token w miejsce symbolu zastępczego.",
      label: "Konfiguracja klienta MCP",
    },
    errors: {
      offline: "Nie można połączyć się z serwerem. Sprawdź połączenie i spróbuj ponownie.",
      tooMany: (max) =>
        `Masz ${plural.pl(max, { one: "# token", few: "# tokeny", many: "# tokenów" })}, czyli najwięcej, ile może mieć jedno konto. Najpierw unieważnij token, którego już nie używasz.`,
      sessionEnded: "Sesja wygasła. Zaloguj się ponownie, aby zarządzać tokenami.",
      invalid:
        "Nazwa lub data wygaśnięcia nie została zaakceptowana. Sprawdź je i spróbuj ponownie.",
      other: (status) => `Coś poszło nie tak (${status}). Spróbuj ponownie.`,
    },
  },
);
