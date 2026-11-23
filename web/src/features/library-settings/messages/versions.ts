import { defineMessages } from "@/shared/lib/i18n";

/** The Versions section: the add form, the table and removing a version. */
export const versionsMessages = defineMessages(
  {
    description:
      "Each version is a branch, tag or commit imported as it was. The filled station is the default.",
    add: "Add a version",
    adding: "Adding",
    addVersion: "Add version",
    /** The credential box when the library has one stored. */
    storedHint: {
      token:
        "Optional. Leave it empty to use the token stored for this library; a new one replaces it.",
      key: "Optional. Leave it empty to use the key stored for this library; a new one replaces it.",
    },
    newHint: "A new one is stored encrypted for this library, replacing any stored one.",
    unlisted:
      "Branches and tags of a private repository are listed with its token or key: enter it above to see them, or type a version below.",
    sameRules: "It is imported with the same paths and tag rules as the other versions.",
    chooseRef: "Choose a branch or tag from the list, or pick “Another ref or commit…”.",
    importingToast: (ref: string) => `Importing ${ref}`,
    importingDescription: "It appears here as soon as the import finishes.",
    defaultNote: " It is the default version, so the library's default moves to another version.",
    removedNewDefault: (ref: string, next: string) =>
      `Removed ${ref}. The default version is now ${next}.`,
    removedLast: (ref: string) => `Removed ${ref}. This library has no versions left.`,
    alreadyRemoved: (ref: string) => `${ref} was already removed.`,
    removedToast: (ref: string) => `Removed ${ref}`,
    newDefault: (next: string) => `The default version is now ${next}.`,
    /** Stands in the dialog title while no version is chosen. */
    versionFallback: "version",
    loss: "Its articles disappear from browse, search and agents now.",
    /** `note`: `defaultNote` when the version is the default, else empty. */
    safe: (note: string) =>
      `Nothing in the repository changes. Content that other versions share stays available. You can add this version again.${note}`,
    confirm: "Remove version",
    table: {
      columns: {
        version: "Version",
        kind: "Kind",
        commit: "Commit",
        origin: "Origin",
        imported: "Imported",
        actions: "Actions",
      },
      kinds: { tag: "tag", branch: "branch", commit: "commit" },
      origins: { manual: "manual", auto: "auto" },
      default: "default",
      /** Beside "default" when an owner pinned it. */
      pinned: "pinned",
      loadFailed: "Couldn't load versions.",
      empty: "No versions yet. Add one, or wait for the first import to finish.",
      find: "Find a version",
      findPlaceholder: "Ref or commit",
      kind: "Kind",
      origin: "Origin",
      imported: "Imported",
      noMatch: "No versions match.",
      noMatchBody: "Try another ref or fewer filters.",
      label: "Imported versions",
      within: {
        "24h": "Last 24 hours",
        "7d": "Last 7 days",
        "30d": "Last 30 days",
      },
      /** What the commit's copy button copies: "Copy commit SHA". */
      commitWhat: "commit SHA",
      actions: {
        browse: "Browse this version",
        copyCommit: "Copy commit SHA",
        copied: "Copied the commit SHA.",
        remove: "Remove version…",
      },
    },
  },
  {
    description:
      "Każda wersja to gałąź, tag lub commit zaimportowany w niezmienionej postaci. Wypełniona stacja oznacza wersję domyślną.",
    add: "Dodaj wersję",
    adding: "Dodawanie",
    addVersion: "Dodaj wersję",
    storedHint: {
      token:
        "Opcjonalne. Zostaw puste, aby użyć tokenu zapisanego dla tej biblioteki; nowy go zastąpi.",
      key: "Opcjonalne. Zostaw puste, aby użyć klucza zapisanego dla tej biblioteki; nowy go zastąpi.",
    },
    newHint:
      "Nowy zostanie zapisany w postaci zaszyfrowanej dla tej biblioteki i zastąpi dotychczasowy.",
    unlisted:
      "Gałęzie i tagi prywatnego repozytorium są wyświetlane dopiero po podaniu jego tokenu lub klucza: wpisz go powyżej, aby je zobaczyć, albo wpisz wersję poniżej.",
    sameRules:
      "Zostanie zaimportowana z tymi samymi ścieżkami i regułami tagów co pozostałe wersje.",
    chooseRef: "Wybierz gałąź lub tag z listy albo wybierz „Inny ref lub commit…”.",
    importingToast: (ref) => `Importowanie ${ref}`,
    importingDescription: "Pojawi się tutaj, gdy tylko import się zakończy.",
    defaultNote: " To wersja domyślna, więc domyślną wersją biblioteki stanie się inna wersja.",
    removedNewDefault: (ref, next) => `Usunięto ${ref}. Wersja domyślna to teraz ${next}.`,
    removedLast: (ref) => `Usunięto ${ref}. W tej bibliotece nie została żadna wersja.`,
    alreadyRemoved: (ref) => `Wersja ${ref} została już usunięta.`,
    removedToast: (ref) => `Usunięto ${ref}`,
    newDefault: (next) => `Wersja domyślna to teraz ${next}.`,
    versionFallback: "wersję",
    loss: "Jej artykuły od razu znikają z przeglądania i wyszukiwania, a agenci tracą do nich dostęp.",
    safe: (note) =>
      `W repozytorium nic się nie zmienia. Treść współdzielona z innymi wersjami pozostaje dostępna. Możesz ponownie dodać tę wersję.${note}`,
    confirm: "Usuń wersję",
    table: {
      columns: {
        version: "Wersja",
        kind: "Rodzaj",
        commit: "Commit",
        origin: "Pochodzenie",
        imported: "Zaimportowano",
        actions: "Działania",
      },
      kinds: { tag: "tag", branch: "gałąź", commit: "commit" },
      origins: { manual: "ręcznie", auto: "automatycznie" },
      default: "domyślna",
      pinned: "przypięta",
      loadFailed: "Nie udało się wczytać wersji.",
      empty:
        "Nie ma jeszcze żadnych wersji. Dodaj wersję albo poczekaj, aż zakończy się pierwszy import.",
      find: "Znajdź wersję",
      findPlaceholder: "Ref lub commit",
      kind: "Rodzaj",
      origin: "Pochodzenie",
      imported: "Zaimportowano",
      noMatch: "Żadna wersja nie pasuje.",
      noMatchBody: "Spróbuj innego refa albo mniejszej liczby filtrów.",
      label: "Zaimportowane wersje",
      within: {
        "24h": "Ostatnie 24 godziny",
        "7d": "Ostatnie 7 dni",
        "30d": "Ostatnie 30 dni",
      },
      commitWhat: "SHA commita",
      actions: {
        browse: "Przeglądaj tę wersję",
        copyCommit: "Kopiuj SHA commita",
        copied: "Skopiowano SHA commita.",
        remove: "Usuń wersję…",
      },
    },
  },
);
