import type { ReactNode } from "react";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";

type SortDirection = false | "asc" | "desc";

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
      loading: "Loading users",
    },
    row: {
      you: "You",
      signsInWith: (provider: string) => `Signs in with ${provider}`,
      password: "Password",
      groups: "Groups: ",
      noGroups: "No groups at the identity provider",
      active: "Active",
      disabled: "Disabled",
      created: "Created ",
      resetNamed: (name: string) => `Reset the password of ${name}`,
      reset: "Reset password",
      enableNamed: (name: string) => `Enable ${name}`,
      enable: "Enable",
      disableNamed: (name: string) => `Disable ${name}`,
      disable: "Disable",
    },
    /** A role as the list, its filter and the create form name it. */
    roles: { user: "User", admin: "Admin" },
    list: {
      columns: { account: "Account", role: "Role", status: "Status", created: "Created" },
      sortBy: (column: string, dir: SortDirection) =>
        `Sort by ${column}${dir ? `, sorted ${dir === "asc" ? "ascending" : "descending"}` : ""}`,
      find: "Find an account",
      usernamePlaceholder: "Username",
      role: "Role",
      anyRole: "Any",
      status: "Status",
      anyStatus: "Any",
      active: "Active",
      disabled: "Disabled",
      sortLabel: "Sort by",
      sort: {
        oldest: "Oldest first",
        newest: "Newest first",
        nameAsc: "Name, A to Z",
        nameDesc: "Name, Z to A",
        adminsFirst: "Admins first",
      },
      noMatchTitle: "No accounts match",
      noMatch: "Nothing matches these filters.",
      clearFilters: "Clear filters",
      label: "User accounts",
      showing: (shown: number, total: number) => `Showing ${shown} of ${total}`,
      loadMore: "Load more",
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
      loading: "Wczytywanie użytkowników",
    },
    row: {
      you: "Ty",
      signsInWith: (provider) => `Logowanie przez ${provider}`,
      password: "Hasło",
      groups: "Grupy: ",
      noGroups: "Brak grup u dostawcy tożsamości",
      active: "Aktywne",
      disabled: "Wyłączone",
      created: "Utworzono ",
      resetNamed: (name) => `Zresetuj hasło użytkownika ${name}`,
      reset: "Zresetuj hasło",
      enableNamed: (name) => `Włącz konto ${name}`,
      enable: "Włącz",
      disableNamed: (name) => `Wyłącz konto ${name}`,
      disable: "Wyłącz",
    },
    roles: { user: "Użytkownik", admin: "Administrator" },
    list: {
      columns: { account: "Konto", role: "Rola", status: "Status", created: "Utworzono" },
      sortBy: (column, dir) =>
        `Sortuj według: ${column}${dir ? `, sortowanie ${dir === "asc" ? "rosnące" : "malejące"}` : ""}`,
      find: "Znajdź konto",
      usernamePlaceholder: "Nazwa użytkownika",
      role: "Rola",
      anyRole: "Dowolna",
      status: "Status",
      anyStatus: "Dowolny",
      active: "Aktywne",
      disabled: "Wyłączone",
      sortLabel: "Sortuj według",
      sort: {
        oldest: "Od najstarszych",
        newest: "Od najnowszych",
        nameAsc: "Nazwa, od A do Z",
        nameDesc: "Nazwa, od Z do A",
        adminsFirst: "Najpierw administratorzy",
      },
      noMatchTitle: "Brak pasujących kont",
      noMatch: "Nic nie pasuje do tych filtrów.",
      clearFilters: "Wyczyść filtry",
      label: "Konta użytkowników",
      showing: (shown, total) =>
        `Wyświetlono ${formatNumber(shown, "pl")} z ${formatNumber(total, "pl")}`,
      loadMore: "Wczytaj więcej",
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
