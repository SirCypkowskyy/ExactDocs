import { defineMessages } from "@/shared/lib/i18n";

/** Why a request from a settings section was refused, in words (`model/settings.ts`). */
export const errorMessages = defineMessages(
  {
    offline: "Can't reach the server. Check your connection and try again.",
    sessionEnded: "Your session ended.",
    signIn: "Sign in",
    noAdmin: "This server has no admin yet.",
    setUp: "Set it up",
    notAllowed: "Your account isn't allowed to change libraries.",
    generic: (status: number) =>
      `Something went wrong on the server (${status}). Try again in a moment.`,
    gone: "This library no longer exists. It may have been removed in another window.",
    refusedValue: "The server refused that value.",
    refusedForm: "The server refused something in the form. Check it and try again.",
    /** `words`: why the profiles could not be read, when that is known. */
    profiles: (words: string | undefined) =>
      `${words ?? "The AI profiles could not be read."} Overrides keep what they have; try again to change them.`,
    addVersion: {
      /** `text`: the server's words, or `commitImported`. */
      sameText: (text: string) =>
        `${text.replace(/\.$/, "")}, so a second version would hold the same text.`,
      commitImported: "This commit is already imported under another version",
      exists: (ref: string) => `“${ref}” is already a version of this library.`,
      resyncBranches: "Branches can be updated with Re-sync",
      importing: (ref: string) => `“${ref}” is being imported right now. Wait for it to finish.`,
      unknownRef: (ref: string) => `This repository has no branch, tag or commit “${ref}”.`,
      ambiguousRef: (ref: string) =>
        `“${ref}” starts more than one commit. Type more characters of the SHA.`,
      credentialsUnreadable:
        "The token or key stored for this library can't be read any more (the server's secret key changed). Enter it again to add this version: it replaces the stored one.",
      authRequired:
        "The repository asks for a login that this library doesn't have, or no longer works. Enter a token or deploy key that can read it: it replaces the stored one.",
      refused: "The server refused that version. Check it and try again.",
    },
    sync: {
      stillImporting:
        "A version is still importing, so there is nothing new to queue. Re-sync once it finishes.",
      authFailed:
        "The stored credentials were refused or can't be read, so nothing changed: send the token or key again. Every version keeps what it served.",
      hostKeyChanged:
        "The SSH host key of the repository's server has changed since it was first seen, so nothing was fetched. Check with whoever runs that server before trusting the new key. Every version keeps what it served.",
      unreadable:
        "The repository couldn't be read (deleted, made private or unreachable), so nothing changed. Every version keeps what it served.",
    },
    reimport: {
      versionGone: "This version no longer exists. It may have been removed in another window.",
      tagNotMoved:
        "The tag points at the commit this version serves again, so there is nothing to re-import.",
      importing: "This version is being imported right now.",
      tagDeleted: "The tag is gone from the repository now. The version keeps serving what it had.",
      notATag: "Only a tag is re-imported this way: a branch is updated with Re-sync.",
      hostKeyChanged:
        "The SSH host key of the repository's server has changed since it was first seen, so nothing was fetched. Check with whoever runs that server before trusting the new key. The version keeps serving what it had.",
      credentials:
        "The stored credentials were refused or can't be read, so nothing changed. The version keeps serving what it had.",
      unreadable:
        "The repository couldn't be read, so nothing changed. The version keeps serving what it had.",
    },
    remove: {
      /** `what`: `library` or `version(ref)`. */
      importRunning: (what: string) =>
        `An import is still running for ${what}. Removing never cancels a job: try again when it finishes.`,
      library: "this library",
      version: (ref: string) => `version ${ref}`,
    },
    settings: {
      invalidPath:
        "One of the paths isn't valid. Use folders, files or globs like docs/ or docs/**/*.md.",
      /** `hint`: what a tag may hold. */
      invalidTag: (hint: string) => `A tag isn't valid. ${hint}`,
      refused: "The server refused something in the paths or tag rules. Check them and try again.",
    },
  },
  {
    offline: "Nie można połączyć się z serwerem. Sprawdź połączenie i spróbuj ponownie.",
    sessionEnded: "Twoja sesja wygasła.",
    signIn: "Zaloguj się",
    noAdmin: "Ten serwer nie ma jeszcze administratora.",
    setUp: "Skonfiguruj go",
    notAllowed: "Twoje konto nie ma uprawnień do zmieniania bibliotek.",
    generic: (status) => `Wystąpił błąd serwera (${status}). Spróbuj ponownie za chwilę.`,
    gone: "Ta biblioteka już nie istnieje. Mogła zostać usunięta w innym oknie.",
    refusedValue: "Serwer odrzucił tę wartość.",
    refusedForm: "Serwer odrzucił część formularza. Sprawdź go i spróbuj ponownie.",
    profiles: (words) =>
      `${words ?? "Nie udało się odczytać profili AI."} Nadpisania zachowują dotychczasowe ustawienia; spróbuj ponownie, aby je zmienić.`,
    addVersion: {
      sameText: (text) =>
        `${text.replace(/\.$/, "")}, więc druga wersja zawierałaby ten sam tekst.`,
      commitImported: "Ten commit jest już zaimportowany jako inna wersja",
      exists: (ref) => `„${ref}” jest już wersją tej biblioteki.`,
      resyncBranches: "Gałęzie można zaktualizować ponowną synchronizacją",
      importing: (ref) =>
        `Wersja „${ref}” jest właśnie importowana. Poczekaj, aż import się zakończy.`,
      unknownRef: (ref) => `To repozytorium nie ma gałęzi, tagu ani commitu „${ref}”.`,
      ambiguousRef: (ref) =>
        `Od „${ref}” zaczyna się więcej niż jeden commit. Wpisz więcej znaków SHA.`,
      credentialsUnreadable:
        "Nie można już odczytać tokenu ani klucza zapisanego dla tej biblioteki (zmienił się tajny klucz serwera). Wpisz go ponownie, aby dodać tę wersję: zastąpi zapisany.",
      authRequired:
        "Repozytorium wymaga logowania, którego ta biblioteka nie ma albo które już nie działa. Wpisz token lub klucz wdrożeniowy z prawem odczytu: zastąpi zapisany.",
      refused: "Serwer odrzucił tę wersję. Sprawdź ją i spróbuj ponownie.",
    },
    sync: {
      stillImporting:
        "Jedna z wersji wciąż jest importowana, więc nie ma nic nowego do kolejki. Zsynchronizuj ponownie, gdy import się zakończy.",
      authFailed:
        "Zapisane dane uwierzytelniające zostały odrzucone lub nie da się ich odczytać, więc nic się nie zmieniło: wyślij token lub klucz ponownie. Każda wersja nadal udostępnia to, co dotąd.",
      hostKeyChanged:
        "Klucz hosta SSH serwera repozytorium zmienił się od pierwszego połączenia, więc niczego nie pobrano. Zanim zaufasz nowemu kluczowi, skontaktuj się z administratorem tego serwera. Każda wersja nadal udostępnia to, co dotąd.",
      unreadable:
        "Nie udało się odczytać repozytorium (zostało usunięte, stało się prywatne lub jest nieosiągalne), więc nic się nie zmieniło. Każda wersja nadal udostępnia to, co dotąd.",
    },
    reimport: {
      versionGone: "Ta wersja już nie istnieje. Mogła zostać usunięta w innym oknie.",
      tagNotMoved:
        "Tag znów wskazuje commit, który udostępnia ta wersja, więc nie ma czego ponownie importować.",
      importing: "Ta wersja jest właśnie importowana.",
      tagDeleted: "Tagu nie ma już w repozytorium. Wersja nadal udostępnia to, co miała.",
      notATag:
        "W ten sposób ponownie importuje się tylko tag: gałąź aktualizuje się ponowną synchronizacją.",
      hostKeyChanged:
        "Klucz hosta SSH serwera repozytorium zmienił się od pierwszego połączenia, więc niczego nie pobrano. Zanim zaufasz nowemu kluczowi, skontaktuj się z administratorem tego serwera. Wersja nadal udostępnia to, co miała.",
      credentials:
        "Zapisane dane uwierzytelniające zostały odrzucone lub nie da się ich odczytać, więc nic się nie zmieniło. Wersja nadal udostępnia to, co miała.",
      unreadable:
        "Nie udało się odczytać repozytorium, więc nic się nie zmieniło. Wersja nadal udostępnia to, co miała.",
    },
    remove: {
      importRunning: (what) =>
        `Import ${what} wciąż trwa. Usuwanie nigdy nie anuluje zadania: spróbuj ponownie, gdy import się zakończy.`,
      library: "tej biblioteki",
      version: (ref) => `wersji ${ref}`,
    },
    settings: {
      invalidPath:
        "Jedna ze ścieżek jest nieprawidłowa. Użyj folderów, plików lub wzorców glob, np. docs/ albo docs/**/*.md.",
      invalidTag: (hint) => `Jeden z tagów jest nieprawidłowy. ${hint}`,
      refused: "Serwer odrzucił coś w ścieżkach lub regułach tagów. Sprawdź je i spróbuj ponownie.",
    },
  },
);
