import type { ReactNode } from "react";
import { defineMessages, plural } from "@/shared/lib/i18n";

const characters = (n: number) => plural.pl(n, { one: "# znak", few: "# znaki", many: "# znaków" });

/** The users slice's strings: the page, its list and filters, the dialogs, the model's errors. */
export const messages = defineMessages(
  {
    page: {
      title: "Users",
      description: (command: ReactNode) => (
        <>
          Accounts on this server. Nobody can sign up: accounts are created here, with {command}, or
          by a first sign-in through an identity provider.
        </>
      ),
      newUser: "New user",
      disabled: (name: string) =>
        `${name} disabled. Their sessions ended and their tokens were revoked.`,
      enabled: (name: string) => `${name} enabled.`,
      disabledToast: (name: string) => `${name} disabled`,
      enabledToast: (name: string) => `${name} enabled`,
      enableFailed: (name: string, why: string) => `Couldn't enable ${name}. ${why}`,
      emptyTitle: "No accounts yet",
      emptyBody: "Create the first account here and pass its password on to its owner.",
      created: (name: string) => `User ${name} created.`,
      createdToast: (name: string) => `User ${name} created`,
      createdHint: "Pass the password on to its owner.",
      passwordChanged: (name: string) =>
        `Password of ${name} changed. They were signed out everywhere.`,
      passwordChangedToast: (name: string) => `Password of ${name} changed`,
      passwordChangedHint: "They were signed out everywhere.",
      disableTitle: (name: string) => `Disable “${name}”?`,
      disableDescription:
        "They are signed out at once, their API tokens are revoked, and they can't sign in until you enable them again.",
      disable: "Disable",
      count: (n: number) => plural.en(n, { one: "# account", other: "# accounts" }),
      loadFailed: "Couldn't load the accounts.",
    },
    row: {
      you: "You",
      password: "Password",
      active: "Active",
      disabled: "Disabled",
    },
    /** A role as the list, its filter and the create form name it. */
    roles: { user: "User", admin: "Admin" },
    list: {
      columns: {
        account: "Account",
        role: "Role",
        status: "Status",
        created: "Created",
        lastActive: "Last active",
        tokens: "Tokens",
      },
      /** No activity yet (or none since the upgrade that started recording it). */
      never: "Never",
      lastActiveHint: "To the hour",
      find: "Find an account",
      usernamePlaceholder: "Username",
      role: "Role",
      status: "Status",
      active: "Active",
      disabled: "Disabled",
      noMatchTitle: "No accounts match",
      noMatch: "Nothing matches these filters.",
      label: "User accounts",
      signIn: "Sign-in",
      groups: "Groups",
      moreGroups: (n: number, name: string) =>
        `${plural.en(n, { one: "# more group", other: "# more groups" })} of ${name}`,
      allGroups: (name: string) => `Groups of ${name}`,
    },
    actions: {
      reset: "Reset password…",
      disable: "Disable…",
      enable: "Enable",
      accessLog: "Show their access-log entries",
      tokens: "Show their API tokens",
    },
    /** The two views of the users page: the accounts, and every account's API tokens. */
    views: { label: "Users views", accounts: "Accounts", tokens: "API tokens" },
    /** Every account's API tokens (operators). */
    tokens: {
      documentTitle: "All API tokens",
      description:
        "Every account's API tokens, expired ones not yet removed included; never their secrets. Disabling an account or resetting its password revokes its tokens.",
      count: (n: number) => plural.en(n, { one: "# token", other: "# tokens" }),
      find: "Find a token",
      findPlaceholder: "Token name",
      label: "API tokens of every account",
      columns: {
        name: "Name",
        owner: "Owner",
        token: "Token",
        libraries: "Libraries",
        created: "Created",
        expires: "Expires",
        used: "Last used",
      },
      prefix: "token prefix",
      allLibraries: "All their libraries",
      noLibraries: "No libraries",
      moreLibraries: (n: number, name: string) =>
        `${plural.en(n, { one: "# more library", other: "# more libraries" })} for ${name}`,
      librariesOf: (name: string) => `Libraries for ${name}`,
      noExpiry: "Never",
      expired: "Expired",
      neverUsed: "Never",
      expiry: "Expiry",
      expiries: { expired: "Expired", valid: "Still valid" },
      use: "Use",
      uses: { unused: "Never used", used: "Used" },
      owner: "Owner",
      ownerTokens: "Show this person's tokens",
      row: (name: string, owner: string) => `${name} (${owner})`,
      emptyTitle: "No API tokens",
      emptyBody: "Tokens show up here once someone creates one under Account → API tokens.",
      noMatchTitle: "No tokens match",
      loadFailed: "Couldn't load the tokens.",
    },
    create: {
      title: "New user",
      description:
        "Choose a first password and pass it on to its owner. They sign in with it right away.",
      username: "Username",
      password: "Password",
      passwordHint: (min: number) => `At least ${min} characters.`,
      repeat: "Repeat password",
      role: "Role",
      roleHint: "An admin also manages user accounts.",
      submit: "Create user",
    },
    reset: {
      title: (name: string) => `Reset the password of “${name}”`,
      description:
        "They are signed out everywhere and their API tokens stop working. Pass the new password on to them.",
      password: "New password",
      passwordHint: (min: number) => `At least ${min} characters.`,
      repeat: "Repeat password",
      submit: "Reset password",
    },
    validation: {
      passwordTooShort: (min: number) => `Use at least ${min} characters.`,
      tooLong: (max: number) => `Use at most ${max} characters.`,
      mismatch: "The passwords don't match.",
      usernameMissing: "Choose a username.",
      noSpaces: "No spaces, please.",
      reserved: (text: string) => `A username can't contain "${text}".`,
    },
    errors: {
      offline: "Can't reach the server. Check your connection and try again.",
      usernameTaken: "Another account already has that username. Pick another one.",
      invalidUsername: "That username isn't accepted: no spaces or control characters.",
      lastOperator:
        "This is the last enabled admin. Make another admin first, or the instance would have nobody to manage accounts.",
      unknownAccount: "That account no longer exists. The list has been refreshed.",
      externalAccount:
        "This account signs in through an identity provider: it has no password to reset.",
      forbidden: "Only an admin can manage user accounts.",
      sessionEnded: "Your session ended. Sign in again to manage users.",
      fieldRefused: (field: "username" | "password", why: string) =>
        `That ${field} isn't accepted: ${why}.`,
      otherFieldRefused: (field: string, why: string) => `The server refused ${field}: ${why}.`,
      requestRefused: (why: string) => `The server refused the request: ${why}.`,
      other: (status: number) => `Something went wrong (${status}). Try again.`,
    },
  },
  {
    page: {
      title: "Użytkownicy",
      description: (command) => (
        <>
          Konta na tym serwerze. Nie ma samodzielnej rejestracji: konto tworzy się tutaj albo
          poleceniem {command}; powstaje też przy pierwszym logowaniu przez dostawcę tożsamości.
        </>
      ),
      newUser: "Nowy użytkownik",
      disabled: (name) => `Wyłączono konto ${name}. Jego sesje zakończono, a tokeny unieważniono.`,
      enabled: (name) => `Włączono konto ${name}.`,
      disabledToast: (name) => `Wyłączono konto ${name}`,
      enabledToast: (name) => `Włączono konto ${name}`,
      enableFailed: (name, why) => `Nie udało się włączyć konta ${name}. ${why}`,
      emptyTitle: "Nie ma jeszcze kont",
      emptyBody: "Utwórz tutaj pierwsze konto i przekaż hasło jego właścicielowi.",
      created: (name) => `Utworzono użytkownika ${name}.`,
      createdToast: (name) => `Utworzono użytkownika ${name}`,
      createdHint: "Przekaż hasło właścicielowi konta.",
      passwordChanged: (name) =>
        `Zmieniono hasło użytkownika ${name}. Wszystkie sesje tego konta zakończono.`,
      passwordChangedToast: (name) => `Zmieniono hasło użytkownika ${name}`,
      passwordChangedHint: "Wszystkie sesje tego konta zakończono.",
      disableTitle: (name) => `Wyłączyć konto „${name}”?`,
      disableDescription:
        "Wszystkie sesje tego konta zostaną od razu zakończone, a jego tokeny API unieważnione. Zalogowanie się będzie niemożliwe, dopóki ponownie nie włączysz konta.",
      disable: "Wyłącz",
      count: (n) => plural.pl(n, { one: "# konto", few: "# konta", many: "# kont" }),
      loadFailed: "Nie udało się wczytać kont.",
    },
    row: {
      you: "Ty",
      password: "Hasło",
      active: "Aktywne",
      disabled: "Wyłączone",
    },
    roles: { user: "Użytkownik", admin: "Administrator" },
    list: {
      columns: {
        account: "Konto",
        role: "Rola",
        status: "Status",
        created: "Utworzono",
        lastActive: "Ostatnia aktywność",
        tokens: "Tokeny",
      },
      never: "Nigdy",
      lastActiveHint: "Z dokładnością do godziny",
      find: "Znajdź konto",
      usernamePlaceholder: "Nazwa użytkownika",
      role: "Rola",
      status: "Status",
      active: "Aktywne",
      disabled: "Wyłączone",
      noMatchTitle: "Brak pasujących kont",
      noMatch: "Nic nie pasuje do tych filtrów.",
      label: "Konta użytkowników",
      signIn: "Logowanie",
      groups: "Grupy",
      moreGroups: (n, name) =>
        `${plural.pl(n, { one: "Jeszcze # grupa", few: "Jeszcze # grupy", many: "Jeszcze # grup" })} użytkownika ${name}`,
      allGroups: (name) => `Grupy użytkownika ${name}`,
    },
    actions: {
      reset: "Zresetuj hasło…",
      disable: "Wyłącz…",
      enable: "Włącz",
      accessLog: "Pokaż wpisy tej osoby w dzienniku dostępu",
      tokens: "Pokaż tokeny API tej osoby",
    },
    views: { label: "Widoki użytkowników", accounts: "Konta", tokens: "Tokeny API" },
    tokens: {
      documentTitle: "Wszystkie tokeny API",
      description:
        "Tokeny API wszystkich kont, łącznie z wygasłymi, których jeszcze nie usunięto; nigdy ich sekrety. Wyłączenie konta lub zresetowanie jego hasła unieważnia jego tokeny.",
      count: (n) => plural.pl(n, { one: "# token", few: "# tokeny", many: "# tokenów" }),
      find: "Znajdź token",
      findPlaceholder: "Nazwa tokenu",
      label: "Tokeny API wszystkich kont",
      columns: {
        name: "Nazwa",
        owner: "Właściciel",
        token: "Token",
        libraries: "Biblioteki",
        created: "Utworzono",
        expires: "Wygasa",
        used: "Ostatnie użycie",
      },
      prefix: "prefiks tokenu",
      allLibraries: "Wszystkie biblioteki właściciela",
      noLibraries: "Brak bibliotek",
      moreLibraries: (n, name) =>
        `${plural.pl(n, { one: "Jeszcze # biblioteka", few: "Jeszcze # biblioteki", many: "Jeszcze # bibliotek" })} tokenu ${name}`,
      librariesOf: (name) => `Biblioteki tokenu ${name}`,
      noExpiry: "Nigdy",
      expired: "Wygasł",
      neverUsed: "Nigdy",
      expiry: "Ważność",
      expiries: { expired: "Wygasłe", valid: "Ważne" },
      use: "Użycie",
      uses: { unused: "Nigdy nieużyte", used: "Użyte" },
      owner: "Właściciel",
      ownerTokens: "Pokaż tokeny tej osoby",
      row: (name, owner) => `${name} (${owner})`,
      emptyTitle: "Brak tokenów API",
      emptyBody: "Tokeny pojawią się tutaj, gdy ktoś utworzy token w sekcji Konto → Tokeny API.",
      noMatchTitle: "Żaden token nie pasuje",
      loadFailed: "Nie udało się wczytać tokenów.",
    },
    create: {
      title: "Nowy użytkownik",
      description:
        "Ustaw pierwsze hasło i przekaż je właścicielowi konta. Może się nim zalogować od razu.",
      username: "Nazwa użytkownika",
      password: "Hasło",
      passwordHint: (min) => `Co najmniej ${characters(min)}.`,
      repeat: "Powtórz hasło",
      role: "Rola",
      roleHint: "Administrator zarządza też kontami użytkowników.",
      submit: "Utwórz użytkownika",
    },
    reset: {
      title: (name) => `Zresetuj hasło użytkownika „${name}”`,
      description:
        "Wszystkie sesje tego konta zostaną zakończone, a jego tokeny API przestaną działać. Przekaż nowe hasło właścicielowi konta.",
      password: "Nowe hasło",
      passwordHint: (min) => `Co najmniej ${characters(min)}.`,
      repeat: "Powtórz hasło",
      submit: "Zresetuj hasło",
    },
    validation: {
      passwordTooShort: (min) => `Użyj co najmniej ${characters(min)}.`,
      tooLong: (max) => `Użyj najwyżej ${characters(max)}.`,
      mismatch: "Hasła się różnią.",
      usernameMissing: "Wybierz nazwę użytkownika.",
      noSpaces: "Nazwa nie może zawierać spacji.",
      reserved: (text) => `Nazwa użytkownika nie może zawierać „${text}”.`,
    },
    errors: {
      offline: "Nie można połączyć się z serwerem. Sprawdź połączenie i spróbuj ponownie.",
      usernameTaken: "Inne konto ma już tę nazwę użytkownika. Wybierz inną.",
      invalidUsername:
        "Ta nazwa użytkownika jest niedozwolona: nie może zawierać spacji ani znaków sterujących.",
      lastOperator:
        "To ostatni włączony administrator. Najpierw nadaj komuś innemu rolę administratora, inaczej w tej instancji nikt nie mógłby zarządzać kontami.",
      unknownAccount: "To konto już nie istnieje. Lista została odświeżona.",
      externalAccount:
        "To konto loguje się przez dostawcę tożsamości: nie ma hasła, które można zresetować.",
      forbidden: "Kontami użytkowników może zarządzać tylko administrator.",
      sessionEnded: "Sesja wygasła. Zaloguj się ponownie, aby zarządzać użytkownikami.",
      fieldRefused: (field, why) =>
        field === "username"
          ? `Ta nazwa użytkownika jest niedozwolona: ${why}.`
          : `To hasło jest niedozwolone: ${why}.`,
      otherFieldRefused: (field, why) => `Serwer odrzucił pole ${field}: ${why}.`,
      requestRefused: (why) => `Serwer odrzucił żądanie: ${why}.`,
      other: (status) => `Coś poszło nie tak (${status}). Spróbuj ponownie.`,
    },
  },
);
