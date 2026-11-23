import { defineMessages } from "@/shared/lib/i18n";
import type { Change } from "./model/access-log";

/** The access log's strings: the pages, the list and its filters, event sentences, errors. */
export const messages = defineMessages(
  {
    pages: {
      title: "Access log",
      libraryTitle: (id: string) => `${id} access log`,
      libraryDescription:
        "Who created, shared, unshared or handed over this library, and when. Newest first.",
      description:
        "Every library's creations, role changes, ownership transfers and removals, with who made them and when. Removed libraries keep their log here. Newest first.",
      libraries: "Libraries",
      sharing: "Sharing",
    },
    list: {
      /** Every change the log records, in the order the filter offers them. */
      changes: {
        granted: "Roles given or changed",
        revoked: "Roles taken away",
        ownership_transferred: "Ownership transfers",
        library_created: "Creations",
        library_deleted: "Removals",
      } satisfies Record<Change, string>,
      library: "Library",
      filter: "Filter",
      libraryInvalid: "Write the library's ID as /owner/repo.",
      libraryHint: "The full ID; removed libraries keep their log.",
      emptyTitle: "Nothing recorded yet",
      emptyBody:
        "Creating, sharing, unsharing and removing a library is recorded here, with who did it and when.",
      noMatchTitle: "No changes match",
      noMatch: "Nothing recorded matches these filters.",
      label: "Access changes, newest first",
      loadFailed: "Couldn't load the access log.",
      /** The table's columns. */
      columns: {
        event: "What happened",
        when: "When",
        library: "Library",
        change: "Change",
        subject: "Who",
        role: "Role",
        by: "By",
      },
      /** One event's change, as a pill. */
      change: {
        granted: "Role given",
        changed: "Role changed",
        revoked: "Role taken away",
        ownership_transferred: "Ownership transferred",
        library_created: "Library created",
        library_deleted: "Library removed",
      },
      /** A role change for screen readers; the screen shows "viewer → admin". */
      fromTo: (from: string, to: string) => `from ${from} to ${to}`,
      actions: {
        openLibrary: "Open library",
        libraryEntries: "Show this library's entries",
      },
      row: (sentence: string, library: string) => `${sentence} (${library})`,
    },
    /** The words of an event's sentence; names and roles go between them. */
    sentence: {
      /** Before a person's name, for languages whose verbs need a grammatical subject. */
      actorBefore: "",
      instance: "ExactDocs (command line or a job)",
      theGroup: "the group ",
      /** A user who is the object of a change ("gave bob", "to bob"). */
      theUser: "",
      created: " created the library",
      deleted: " removed the library and every role on it",
      transferred: " transferred ownership to ",
      revoked: " took the ",
      revokedFrom: " role from ",
      changed: " changed ",
      changedFrom: " from ",
      changedTo: " to ",
      gave: " gave ",
      gaveThe: " the ",
      gaveTail: " role",
      /** A role as the server names it; an unknown one shows as sent. */
      roles: {
        viewer: "viewer",
        contributor: "contributor",
        admin: "admin",
        creator: "creator",
      } as Record<string, string>,
    },
    errors: {
      offline: "Can't reach the server. Check your connection and try again.",
      sessionEnded: "Your session ended. Sign in again to read the access log.",
      forbidden: "Only the library's admins and the server's operators can read its access log.",
      notFound: "This library doesn't exist, or you have no access to it.",
      invalidCursor: "The list moved on. Reload the page to start over.",
      other: (status: number) => `Something went wrong (${status}). Try again.`,
    },
  },
  {
    pages: {
      title: "Dziennik dostępu",
      libraryTitle: (id) => `Dziennik dostępu ${id}`,
      libraryDescription:
        "Kto i kiedy utworzył tę bibliotekę, udostępnił ją, cofnął jej udostępnienie lub ją przekazał. Od najnowszych.",
      description:
        "Utworzenia, zmiany ról, przekazania własności i usunięcia wszystkich bibliotek, z informacją, kto i kiedy ich dokonał. Usunięte biblioteki zachowują tu swój dziennik. Od najnowszych.",
      libraries: "Biblioteki",
      sharing: "Udostępnianie",
    },
    list: {
      changes: {
        granted: "Nadane lub zmienione role",
        revoked: "Odebrane role",
        ownership_transferred: "Przekazania własności",
        library_created: "Utworzenia bibliotek",
        library_deleted: "Usunięcia bibliotek",
      },
      library: "Biblioteka",
      filter: "Filtruj",
      libraryInvalid: "Wpisz identyfikator biblioteki w postaci /owner/repo.",
      libraryHint: "Pełny identyfikator; usunięte biblioteki zachowują swój dziennik.",
      emptyTitle: "Nic jeszcze nie zarejestrowano",
      emptyBody:
        "Tutaj rejestrowane jest utworzenie, udostępnienie, cofnięcie udostępnienia i usunięcie biblioteki, z informacją, kto i kiedy to zrobił.",
      noMatchTitle: "Brak pasujących zmian",
      noMatch: "Żaden wpis nie pasuje do tych filtrów.",
      label: "Zmiany dostępu, od najnowszych",
      loadFailed: "Nie udało się wczytać dziennika dostępu.",
      columns: {
        event: "Co się stało",
        when: "Kiedy",
        library: "Biblioteka",
        change: "Zmiana",
        subject: "Kto",
        role: "Rola",
        by: "Autor zmiany",
      },
      change: {
        granted: "Nadana rola",
        changed: "Zmieniona rola",
        revoked: "Odebrana rola",
        ownership_transferred: "Przekazana własność",
        library_created: "Utworzona biblioteka",
        library_deleted: "Usunięta biblioteka",
      },
      fromTo: (from, to) => `z ${from} na ${to}`,
      actions: {
        openLibrary: "Otwórz bibliotekę",
        libraryEntries: "Pokaż wpisy tej biblioteki",
      },
      row: (sentence, library) => `${sentence} (${library})`,
    },
    // Polish verbs in the past tense carry a gender, so the sentence names the actor as
    // "Użytkownik alice" (a masculine noun, whoever the person is) and the verbs agree with it.
    sentence: {
      actorBefore: "Użytkownik ",
      instance: "ExactDocs (wiersz poleceń lub zadanie)",
      theGroup: "grupie ",
      theUser: "użytkownikowi ",
      created: " utworzył bibliotekę",
      deleted: " usunął bibliotekę i wszystkie przypisane do niej role",
      transferred: " przekazał własność ",
      revoked: " odebrał rolę ",
      revokedFrom: " ",
      changed: " zmienił ",
      changedFrom: " rolę z ",
      changedTo: " na ",
      gave: " nadał ",
      gaveThe: " rolę ",
      gaveTail: "",
      roles: {
        viewer: "czytelnik",
        contributor: "współtwórca",
        admin: "administrator",
        creator: "twórca",
      },
    },
    errors: {
      offline: "Nie można połączyć się z serwerem. Sprawdź połączenie i spróbuj ponownie.",
      sessionEnded: "Sesja wygasła. Zaloguj się ponownie, aby przeglądać dziennik dostępu.",
      forbidden:
        "Dziennik dostępu biblioteki mogą przeglądać tylko jej administratorzy i operatorzy serwera.",
      notFound: "Ta biblioteka nie istnieje albo nie masz do niej dostępu.",
      invalidCursor: "Lista się zmieniła. Odśwież stronę, aby zacząć od początku.",
      other: (status) => `Coś poszło nie tak (${status}). Spróbuj ponownie.`,
    },
  },
);
