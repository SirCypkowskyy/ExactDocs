import type { ReactNode } from "react";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";

/** Strings of the add-library flow: the form, its steps, the file preview, and its refusals. */

const tryAgainInEn = (seconds: number | undefined) =>
  `Try again in ${seconds ? `${seconds} ${plural.en(seconds, { one: "second", other: "seconds" })}` : "a moment"}.`;

const tryAgainInPl = (seconds: number | undefined) =>
  seconds
    ? `Spróbuj ponownie za ${plural.pl(seconds, { one: "# sekundę", few: "# sekundy", many: "# sekund" })}.`
    : "Spróbuj ponownie za chwilę.";

export const addMessages = defineMessages(
  {
    title: "Add a library",
    importTitle: "Import",
    description:
      "Point ExactDocs at a git repository with Markdown docs. It imports one version at a time, exactly as it was.",
    importDescription: "Reading the repository and indexing its documents.",
    backToList: "Libraries",
    addLibrary: "Add library",
    adding: "Adding",
    checkRepository: "Check repository",
    checking: "Checking",
    steps: {
      label: "Steps",
      stepOf: (step: number, total: number) => `Step ${step} of ${total}: `,
      done: " (done)",
      failed: " (failed)",
      check: { label: "Check repository", hint: "Is it reachable?" },
      choose: { label: "Choose version", hint: "Branch, tag or commit" },
      files: { label: "Choose files", hint: "Optional" },
      import: { label: "Import", hint: "Reads and indexes it" },
    },
    address: {
      label: "Repository address",
      hint: "A git repository with Markdown docs.",
      openLibrary: (id: string) => `Open ${id}`,
      hosts: {
        github: "GitHub",
        gitlab: "GitLab",
        bitbucket: "Bitbucket",
        gitea: "Gitea",
        git: "a git server",
      },
      foundOn: (host: string) => `Found on ${host}.`,
      defaultBranch: (branch: string) => `Default branch is ${branch}.`,
      noDefaultBranch: "It has no default branch, so choose one below.",
      hostKeyTitle: "SSH host key of the server",
      hostKeyHint:
        "Compare it with the fingerprint your git host publishes before you add the library. If they differ, don't add it: someone may be in the middle.",
      private: "This repository is private",
      privateNeedsAddress:
        "A private repository needs an https:// address (with an access token) or an ssh:// or git@host:path address (with a deploy key).",
      credentialNeedsAddress:
        "A token needs an https:// address, and a deploy key an ssh:// or git@host:path address.",
    },
    libraryId: {
      label: "Library ID",
      hint: "How agents refer to this library, as /owner/repo.",
    },
    added: {
      toast: (id: string) => `Added ${id}`,
      description: (ref: string) => `Importing ${ref} now. You can leave this page.`,
    },
    advanced: {
      summary: "Choose files and tags",
    },
    preview: {
      button: "Preview",
      pending: "Previewing",
      hint: "See which files this version and these paths take, before importing.",
      selectionHint: (version: ReactNode): ReactNode =>
        version ? (
          <>See which files these paths take in {version}, before saving.</>
        ) : (
          "See which files these paths take in the default branch, before saving."
        ),
      filesToImport: "Files to import",
      filesTaken: "Files these paths take",
      commit: " commit",
      stale: "The form changed since this preview. Preview again to see the files it takes now.",
      matchingFiles: "Matching files",
      noneMatch: "No Markdown files match.",
      filesMatch: (n: number) => plural.en(n, { one: "# file matches.", other: "# files match." }),
      firstListed: (n: number) => `The first ${formatNumber(n, "en")} are listed.`,
      context7: {
        found: "This repository has a context7.json.",
        ignored: "This repository's context7.json is ignored.",
        title: "Title:",
        description: "Description:",
        prefilled:
          "Its paths are filled in under “Choose files and tags”. Change them if you like.",
        rules: (n: number) =>
          plural.en(n, {
            one: "Its rule is shown to agents with every answer.",
            other: `Its ${n} rules are shown to agents with every answer.`,
          }),
      },
      older: {
        legend: "Also import older versions",
        hint: "The repository's context7.json offers these tags. Each one ticked is imported after the library is added.",
        title: "Older versions",
        retry: (tag: string) => `Try again to import ${tag}`,
        waiting: "Waiting to be queued",
        notQueued: (why: string) => `Not queued. ${why}`,
      },
    },
    errors: {
      urlEmpty: "Paste the address of a git repository.",
      urlTooLong: "That address is too long. Addresses can be up to 2048 characters.",
      urlSpaces: "An address has no spaces. Paste it again.",
      urlCredentials:
        "Remove the username and password from the address. For a private repository, give its token under “This repository is private”.",
      urlScheme:
        "That isn't a repository address yet. Start with https://, like https://github.com/acme/payments.",
      libraryIdForm: "Use the form /owner/repo, like /acme/payments.",
      sessionEnded: "Your session ended.",
      signIn: "Sign in",
      noAdmin: "This server has no admin yet.",
      setUp: "Set it up",
      forbidden: "Your account isn't allowed to add libraries.",
      server: (status: number) =>
        `Something went wrong on the server (${status}). Try again in a moment.`,
      offline: "Can't reach the server. Check your connection and try again.",
      invalidUrl:
        "That doesn't look like a git repository address. Try https://github.com/owner/repo.",
      notARepository:
        "No git repository there. Check the address; a private repository looks the same.",
      authRequired:
        "That repository asks for a login. If it is private, give a token or deploy key that can read it.",
      unreachable: "Couldn't reach that address. Check it, and that the server can get online.",
      noGit: "The server has no git installed, so it can't read repositories.",
      idTakenBy: (id: string) => `A library with this repository's ID, ${id}, already exists.`,
      idTakenByRepository: "A library with this repository's ID already exists.",
      busyReading: (seconds: number | undefined) =>
        `The server is busy reading other repositories, so it couldn't read this one's context7.json. ${tryAgainInEn(seconds)}`,
      busyPreviewing: (seconds: number | undefined) =>
        `The server is busy previewing other repositories. ${tryAgainInEn(seconds)}`,
      idTaken: "That ID is already used by another library. Choose another.",
      unknownRef: (ref: string) => `This repository has no branch, tag or commit “${ref}”.`,
      noDefaultBranch: "This repository has no default branch. Choose a tag or a branch.",
      ambiguousRef: (ref: string) =>
        `“${ref}” starts more than one commit. Type more characters of the SHA.`,
      invalidPath:
        "One of the paths isn't valid. Use folders, files or globs like docs/ or docs/**/*.md.",
      invalidTag: (hint: string) => `A tag isn't valid. ${hint}`,
      noArticles:
        "No Markdown files match these paths. Widen them, or clear them to take every .md, .mdx and .rst file.",
      refused: "Check the form and try again. The server refused something in it.",
      importing: "Already being imported.",
      versionExists: "Already a version of this library.",
      sameCommitAs: (version: string) => `Same commit as version ${version}, already imported.`,
      sameCommit: "Same commit as a version already imported.",
    },
    skipReasons: {
      binary: "Binary files",
      too_large: "Over the size limit (2 MiB)",
      undecodable: "Not readable as text",
      not_a_file: "Not regular files (symlinks)",
      unreadable: "Couldn't be read",
      bad_file_name: "File names that aren't valid UTF-8",
      unparsable: "Couldn't be parsed or split into chunks",
      other: "Skipped",
    },
  },
  {
    title: "Dodaj bibliotekę",
    importTitle: "Import",
    description:
      "Wskaż ExactDocs repozytorium git z dokumentacją w formacie Markdown. Każda wersja jest importowana osobno, dokładnie w takim stanie, w jakim była.",
    importDescription: "Odczytywanie repozytorium i indeksowanie jego dokumentów.",
    backToList: "Biblioteki",
    addLibrary: "Dodaj bibliotekę",
    adding: "Dodawanie",
    checkRepository: "Sprawdź repozytorium",
    checking: "Sprawdzanie",
    steps: {
      label: "Kroki",
      stepOf: (step, total) => `Krok ${step} z ${total}: `,
      done: " (ukończono)",
      failed: " (błąd)",
      check: { label: "Sprawdzenie repozytorium", hint: "Czy jest dostępne?" },
      choose: { label: "Wybór wersji", hint: "Gałąź, tag lub commit" },
      files: { label: "Wybór plików", hint: "Opcjonalnie" },
      import: { label: "Import", hint: "Odczyt i indeksowanie" },
    },
    address: {
      label: "Adres repozytorium",
      hint: "Repozytorium git z dokumentacją w formacie Markdown.",
      openLibrary: (id) => `Otwórz ${id}`,
      hosts: {
        github: "GitHubie",
        gitlab: "GitLabie",
        bitbucket: "Bitbuckecie",
        gitea: "serwerze Gitea",
        git: "serwerze git",
      },
      foundOn: (host) => `Znaleziono na ${host}.`,
      defaultBranch: (branch) => `Domyślna gałąź to ${branch}.`,
      noDefaultBranch: "Nie ma domyślnej gałęzi, więc wybierz ją poniżej.",
      hostKeyTitle: "Klucz hosta SSH serwera",
      hostKeyHint:
        "Zanim dodasz bibliotekę, porównaj go z odciskiem klucza publikowanym przez Twój serwis git. Jeśli się różnią, nie dodawaj jej: ktoś może przechwytywać połączenie.",
      private: "To repozytorium jest prywatne",
      privateNeedsAddress:
        "Prywatne repozytorium wymaga adresu https:// (z tokenem dostępu) albo adresu ssh:// lub git@host:path (z kluczem wdrożeniowym).",
      credentialNeedsAddress:
        "Token wymaga adresu https://, a klucz wdrożeniowy adresu ssh:// lub git@host:path.",
    },
    libraryId: {
      label: "Identyfikator biblioteki",
      hint: "Nazwa, pod którą agenci odwołują się do tej biblioteki, w postaci /owner/repo.",
    },
    added: {
      toast: (id) => `Dodano ${id}`,
      description: (ref) => `Trwa import ${ref}. Możesz opuścić tę stronę.`,
    },
    advanced: {
      summary: "Wybierz pliki i tagi",
    },
    preview: {
      button: "Pokaż podgląd",
      pending: "Tworzenie podglądu",
      hint: "Sprawdź przed importem, które pliki obejmują ta wersja i te ścieżki.",
      selectionHint: (version) =>
        version ? (
          <>Sprawdź przed zapisaniem, które pliki obejmują te ścieżki w wersji {version}.</>
        ) : (
          "Sprawdź przed zapisaniem, które pliki obejmują te ścieżki w domyślnej gałęzi."
        ),
      filesToImport: "Pliki do zaimportowania",
      filesTaken: "Pliki objęte tymi ścieżkami",
      commit: " commit",
      stale:
        "Formularz zmienił się od tego podglądu. Pokaż podgląd ponownie, aby zobaczyć, które pliki obejmuje teraz.",
      matchingFiles: "Pasujące pliki",
      noneMatch: "Żaden plik Markdown nie pasuje.",
      filesMatch: (n) =>
        plural.pl(n, { one: "# plik pasuje.", few: "# pliki pasują.", many: "# plików pasuje." }),
      firstListed: (n) =>
        plural.pl(n, {
          one: "Wyświetlono pierwszy z nich.",
          few: "Wyświetlono pierwsze #.",
          many: "Wyświetlono pierwszych #.",
        }),
      context7: {
        found: "To repozytorium ma plik context7.json.",
        ignored: "Plik context7.json tego repozytorium jest pomijany.",
        title: "Tytuł:",
        description: "Opis:",
        prefilled: "Jego ścieżki wpisano w sekcji „Wybierz pliki i tagi”. Możesz je zmienić.",
        rules: (n) =>
          plural.pl(n, {
            one: "Jego reguła jest pokazywana agentom przy każdej odpowiedzi.",
            few: "Jego # reguły są pokazywane agentom przy każdej odpowiedzi.",
            many: "Jego # reguł jest pokazywanych agentom przy każdej odpowiedzi.",
          }),
      },
      older: {
        legend: "Zaimportuj też starsze wersje",
        hint: "Plik context7.json repozytorium proponuje te tagi. Każdy zaznaczony zostanie zaimportowany po dodaniu biblioteki.",
        title: "Starsze wersje",
        retry: (tag) => `Spróbuj ponownie zaimportować ${tag}`,
        waiting: "Czeka na dodanie do kolejki",
        notQueued: (why) => `Nie dodano do kolejki. ${why}`,
      },
    },
    errors: {
      urlEmpty: "Wklej adres repozytorium git.",
      urlTooLong: "Ten adres jest za długi. Adres może mieć najwyżej 2048 znaków.",
      urlSpaces: "Adres nie może zawierać spacji. Wklej go ponownie.",
      urlCredentials:
        "Usuń z adresu nazwę użytkownika i hasło. W przypadku prywatnego repozytorium podaj jego token w sekcji „To repozytorium jest prywatne”.",
      urlScheme:
        "To jeszcze nie jest adres repozytorium. Zacznij od https://, np. https://github.com/acme/payments.",
      libraryIdForm: "Użyj postaci /owner/repo, np. /acme/payments.",
      sessionEnded: "Twoja sesja wygasła.",
      signIn: "Zaloguj się",
      noAdmin: "Ten serwer nie ma jeszcze administratora.",
      setUp: "Skonfiguruj go",
      forbidden: "Twoje konto nie ma uprawnień do dodawania bibliotek.",
      server: (status) => `Wystąpił błąd na serwerze (${status}). Spróbuj ponownie za chwilę.`,
      offline: "Nie można połączyć się z serwerem. Sprawdź połączenie i spróbuj ponownie.",
      invalidUrl:
        "To nie wygląda na adres repozytorium git. Spróbuj https://github.com/owner/repo.",
      notARepository:
        "Pod tym adresem nie ma repozytorium git. Sprawdź adres; prywatne repozytorium wygląda tak samo.",
      authRequired:
        "To repozytorium wymaga logowania. Jeśli jest prywatne, podaj token lub klucz wdrożeniowy z prawem odczytu.",
      unreachable:
        "Nie udało się połączyć z tym adresem. Sprawdź go oraz to, czy serwer ma dostęp do internetu.",
      noGit: "Na serwerze nie zainstalowano gita, więc nie może on odczytywać repozytoriów.",
      idTakenBy: (id) => `Biblioteka o identyfikatorze tego repozytorium, ${id}, już istnieje.`,
      idTakenByRepository: "Biblioteka o identyfikatorze tego repozytorium już istnieje.",
      busyReading: (seconds) =>
        `Serwer jest zajęty odczytywaniem innych repozytoriów, więc nie mógł odczytać pliku context7.json tego repozytorium. ${tryAgainInPl(seconds)}`,
      busyPreviewing: (seconds) =>
        `Serwer jest zajęty tworzeniem podglądów innych repozytoriów. ${tryAgainInPl(seconds)}`,
      idTaken: "Ten identyfikator jest już używany przez inną bibliotekę. Wybierz inny.",
      unknownRef: (ref) => `To repozytorium nie ma gałęzi, tagu ani commita „${ref}”.`,
      noDefaultBranch: "To repozytorium nie ma domyślnej gałęzi. Wybierz tag lub gałąź.",
      ambiguousRef: (ref) =>
        `Od „${ref}” zaczyna się więcej niż jeden commit. Wpisz więcej znaków SHA.`,
      invalidPath:
        "Jedna ze ścieżek jest nieprawidłowa. Użyj folderów, plików lub wzorców glob, np. docs/ lub docs/**/*.md.",
      invalidTag: (hint) => `Tag jest nieprawidłowy. ${hint}`,
      noArticles:
        "Żaden plik Markdown nie pasuje do tych ścieżek. Poszerz je albo wyczyść, aby objąć wszystkie pliki .md, .mdx i .rst.",
      refused: "Sprawdź formularz i spróbuj ponownie. Serwer odrzucił część danych.",
      importing: "Ta wersja jest już importowana.",
      versionExists: "To już jest wersja tej biblioteki.",
      sameCommitAs: (version) => `Ten sam commit co wersja ${version}, już zaimportowana.`,
      sameCommit: "Ten sam commit co już zaimportowana wersja.",
    },
    skipReasons: {
      binary: "Pliki binarne",
      too_large: "Przekraczają limit rozmiaru (2 MiB)",
      undecodable: "Nie dają się odczytać jako tekst",
      not_a_file: "Nie są zwykłymi plikami (dowiązania symboliczne)",
      unreadable: "Nie udało się ich odczytać",
      bad_file_name: "Nazwy plików niebędące poprawnym UTF-8",
      unparsable: "Nie udało się ich przetworzyć ani podzielić na fragmenty",
      other: "Pominięte",
    },
  },
);
