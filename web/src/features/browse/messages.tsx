import type { ReactNode } from "react";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";
import type { Version } from "./model/browse";

/*
 * The browse slice's strings: the library page, the article pane, the file tree, the version
 * picker, the tag editor and the renderer's own controls. The documentation itself (titles, text,
 * paths, refs, the name of a callout as the file writes it) is the library's and stays as it is.
 */

type RefKind = Version["kind"];
const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

export const messages = defineMessages(
  {
    page: {
      browsing: (ref: ReactNode) => <>Browsing {ref}</>,
      readArticle: "Read an article",
      readArticleHint: (sha: ReactNode) => (
        <>Pick a file from the tree. The text is exactly as imported from commit {sha}.</>
      ),
      searchVersion: (ref: string) => `Search ${ref}`,
      searchHint: "Every article of this version, and nothing from another one",
      press: (key: ReactNode) => <>(press {key})</>,
      breadcrumb: "Breadcrumb",
      libraries: "Libraries",
      opensRepository: "(opens the repository)",
      imported: (kind: RefKind) => (kind === "tag" ? "Imported" : `${capitalize(kind)} · imported`),
      share: "Share",
      settings: "Settings",
      nothingImported: "Nothing imported yet",
      noVersions: "This library has no versions. Once its first import finishes they appear here.",
      searchRegion: "Search",
      articleRegion: "Article",
      loading: "Loading the library",
      unknownVersion: (missing: ReactNode, shown: ReactNode) => (
        <>
          {missing} is not an imported version of this library. Showing {shown} instead.
        </>
      ),
    },
    table: {
      articles: "Articles",
      findArticle: "Find an article",
      pathOrTitle: "Path or title",
      path: "Path",
      title: "Title",
      tags: "Tags",
      moreTags: (n: number, path: string) =>
        `${plural.en(n, { one: "# more tag", other: "# more tags" })} of ${path}`,
      tagsOf: (path: string) => `Tags of ${path}`,
      size: "Size",
      loadFailed: "Couldn't load articles.",
      retry: "Retry",
      noMatch: "No articles match these filters.",
      none: "No articles.",
      count: (count: number) => plural.en(count, { one: "# article", other: "# articles" }),
      folder: "Folder",
      open: "Open",
      copyPath: "Copy path",
      copyLink: "Copy link to this version",
      openOn: (host: string | undefined) => `Open on ${host ?? "the host"}`,
      inFolder: "Show this folder's articles",
      pathCopied: "Path copied",
      linkCopied: "Link copied",
    },
    notFound: {
      title: "Library not found",
      allLibraries: "All libraries",
      body: (name: ReactNode) => (
        <>ExactDocs has no library {name}. Check the address, or pick one from the list.</>
      ),
    },
    article: {
      viewFileOn: (host: string | undefined) => `View file on ${host ?? "the host"}`,
      viewOn: (host: string | undefined) => `View on ${host ?? "the host"}`,
      atCommit: (sha: string) => `at commit ${sha} (opens a new tab)`,
      commit: "Commit",
      opensNewTab: "(opens a new tab)",
      notIn: (ref: ReactNode) => <>Not in {ref}</>,
      hasNo: (ref: string, path: ReactNode) => (
        <>
          {ref} has no {path}. It may have been added later, moved or removed.
        </>
      ),
      closeMatches: (ref: string) => `Close matches in ${ref}`,
      showRoot: (ref: string) => `Show the root of ${ref}`,
      openPathIn: (ref: string) => `Open this path in ${ref}`,
      view: "View",
      rendered: "Rendered",
      source: "Source",
      mdxNotice: "MDX: imports and components are shown as source, not run.",
      rendererFailed: "Couldn't load the article renderer.",
      rendererFailedHint:
        "Your connection may have dropped, or ExactDocs was updated. The file itself is fine.",
      viewSource: "View source",
      sourceText: "Source text",
      largeFile: (kb: number) => `This file is ${kb} kB, so it opens as source.`,
      renderAnyway: "Render it anyway",
      movedFrom: (path: ReactNode, ref: string) => (
        <>
          Moved from {path} in {ref}
        </>
      ),
      articleText: "Article text",
      contents: "Contents",
      loading: (path: string) => `Loading ${path}`,
      loadFailed: "Couldn't load this article",
      noAnswer: "ExactDocs didn't answer. Check that it is running, then try again.",
      onThisPage: "On this page",
      sections: (count: number) => plural.en(count, { one: "# section", other: "# sections" }),
    },
    tree: {
      files: "Files",
      browseFiles: "Browse files",
      filesOf: (ref: string) => `Files of ${ref}`,
      loadingFiles: "Loading files",
      filesFailed: (ref: string) => `Couldn't load the files of ${ref}.`,
      noneTagged: (tags: readonly string[]) => `No articles tagged ${tags.join(" or ")}`,
      nothingHere: "Nothing imported here",
      noneWithTags: (ref: string, count: number) =>
        `${ref} has no article with ${count > 1 ? "any of these tags" : "this tag"}.`,
      noArticles: (ref: string) =>
        `${ref} has no articles. Its import may have skipped every file.`,
      showAll: "Show all articles",
      moreFailed: (folder: string) => `Couldn't load ${folder || "more files"}. Try again`,
      loadingMore: "Loading more",
      showMore: (folder: string) => (folder ? `Show more in ${folder}` : "Show more files"),
      file: "File",
      loading: "Loading",
    },
    versions: {
      default: "default",
      pinnedDefault: "pinned default",
      trigger: (ref: string) => `Version: ${ref}. Change version`,
      switching: (ref: string, to: string) => `Version: ${ref}, switching to ${to}. Change version`,
      filterPlaceholder: (count: number) =>
        plural.en(count, { one: "Filter # version", other: "Filter # versions" }),
      filter: "Filter versions",
      list: "Versions",
      kind: { branch: "branch", commit: "commit" },
      noMatch: (filter: string) => `No version matches "${filter}".`,
      gone: "That version or library is no longer imported. Reload the page.",
      signIn: "Sign in again to change this.",
      changeFailed: "The default could not be changed. Try again.",
      setToast: "Default version set",
      unpinnedToast: "Default version unpinned",
      followsRule: "It follows the default-version rule again.",
      setTo: (ref: string) => `Default version set to ${ref}.`,
      unpinned: "Default version unpinned.",
      pinAs: (ref: ReactNode) => <>Pin {ref} as default</>,
      unpin: "Unpin default",
      backToAutomatic: "back to automatic",
    },
    tags: {
      invalid: (max: number) =>
        `A tag starts with a letter or digit and goes on with letters, digits and . _ + - (${max} characters at most).`,
      duplicate: "This article already has that tag.",
      tooMany: (max: number) => `An article path takes at most ${max} tags by hand.`,
      signIn: "Sign in again to change tags.",
      gone: "This library is no longer imported. Reload the page.",
      saveFailed: "The tags could not be saved. Try again.",
      setOn: (path: ReactNode) => <>set on {path}</>,
      removeTag: (tag: string) => `Remove tag ${tag}`,
      removeTagSetOn: (tag: string, path: string) => `Remove tag ${tag}, set on ${path}`,
      newTag: "New tag",
      add: "Add",
      hint: "For this path in every version of the library, and where it was renamed to later.",
      added: "Tag added",
      removed: "Tag removed",
      undo: "Undo",
      region: "Tags",
      fromFile: "From the file",
      fromFrontMatter: "Tags from front matter",
      fromRules: "From path rules",
      fromRulesList: "Tags from path rules",
      imported: "Imported",
      importedList: "Tags from front matter or path rules",
      importedNote:
        "This version was imported before ExactDocs kept which is which. Importing it again, or changing a tag rule, tells them apart.",
      addedHere: "Added here",
      addedList: "Tags added by hand",
      addTag: "Add tag",
      kept: (tag: string) => `${tag} stays on this article: its import gives it too.`,
    },
    render: {
      pressCtrlC: "Press Ctrl+C",
      copyFailed: "Copy failed",
      code: "code",
      file: "file",
      plainText: "Text",
      noImage: (alt: string) => `Image not available: ${alt || "Image"}`,
      linkTo: (heading: string) => `Link to ${heading}`,
      done: "Done",
      notDone: "Not done",
      table: (name: string) => (name ? `Table: ${name}` : "Table"),
      variant: { note: "Note", tip: "Tip", warning: "Warning", danger: "Danger" },
    },
  },
  {
    page: {
      browsing: (ref) => <>Przeglądasz {ref}</>,
      readArticle: "Przeczytaj artykuł",
      readArticleHint: (sha) => (
        <>Wybierz plik z drzewa. Tekst jest dokładnie taki, jak zaimportowano go z commita {sha}.</>
      ),
      searchVersion: (ref) => `Przeszukaj ${ref}`,
      searchHint: "Wszystkie artykuły tej wersji i nic spoza niej",
      press: (key) => <>(naciśnij {key})</>,
      breadcrumb: "Ścieżka nawigacji",
      libraries: "Biblioteki",
      opensRepository: "(otwiera repozytorium)",
      imported: (kind) =>
        ({
          tag: "Zaimportowano",
          branch: "Gałąź · zaimportowano",
          commit: "Commit · zaimportowano",
        })[kind],
      share: "Udostępnij",
      settings: "Ustawienia",
      nothingImported: "Nic jeszcze nie zaimportowano",
      noVersions:
        "Ta biblioteka nie ma wersji. Pojawią się tutaj, gdy skończy się jej pierwszy import.",
      searchRegion: "Wyszukiwanie",
      articleRegion: "Artykuł",
      loading: "Wczytywanie biblioteki",
      unknownVersion: (missing, shown) => (
        <>
          {missing} nie jest zaimportowaną wersją tej biblioteki. Wyświetlana jest wersja {shown}.
        </>
      ),
    },
    table: {
      articles: "Artykuły",
      findArticle: "Znajdź artykuł",
      pathOrTitle: "Ścieżka lub tytuł",
      path: "Ścieżka",
      title: "Tytuł",
      tags: "Tagi",
      moreTags: (n, path) =>
        `${plural.pl(n, { one: "Jeszcze # tag", few: "Jeszcze # tagi", many: "Jeszcze # tagów" })}: ${path}`,
      tagsOf: (path) => `Tagi: ${path}`,
      size: "Rozmiar",
      loadFailed: "Nie udało się wczytać artykułów.",
      retry: "Ponów",
      noMatch: "Żaden artykuł nie pasuje do tych filtrów.",
      none: "Brak artykułów.",
      count: (count) =>
        plural.pl(count, { one: "# artykuł", few: "# artykuły", many: "# artykułów" }),
      folder: "Folder",
      open: "Otwórz",
      copyPath: "Kopiuj ścieżkę",
      copyLink: "Kopiuj link do tej wersji",
      openOn: (host) => (host ? `Otwórz w serwisie ${host}` : "Otwórz w repozytorium"),
      inFolder: "Pokaż artykuły z tego folderu",
      pathCopied: "Skopiowano ścieżkę",
      linkCopied: "Skopiowano link",
    },
    notFound: {
      title: "Nie znaleziono biblioteki",
      allLibraries: "Wszystkie biblioteki",
      body: (name) => (
        <>ExactDocs nie ma biblioteki {name}. Sprawdź adres albo wybierz bibliotekę z listy.</>
      ),
    },
    article: {
      viewFileOn: (host) =>
        host ? `Zobacz plik w serwisie ${host}` : "Zobacz plik w repozytorium",
      viewOn: (host) => (host ? `Zobacz w serwisie ${host}` : "Zobacz w repozytorium"),
      atCommit: (sha) => `w commicie ${sha} (otwiera się w nowej karcie)`,
      commit: "Commit",
      opensNewTab: "(otwiera się w nowej karcie)",
      notIn: (ref) => <>Brak w wersji {ref}</>,
      hasNo: (ref, path) => (
        <>
          W {ref} nie ma pliku {path}. Mógł zostać dodany później, przeniesiony lub usunięty.
        </>
      ),
      closeMatches: (ref) => `Podobne ścieżki w ${ref}`,
      showRoot: (ref) => `Pokaż katalog główny ${ref}`,
      openPathIn: (ref) => `Otwórz tę ścieżkę w ${ref}`,
      view: "Widok",
      rendered: "Podgląd",
      source: "Źródło",
      mdxNotice: "MDX: importy i komponenty są pokazane jako kod źródłowy, a nie uruchamiane.",
      rendererFailed: "Nie udało się wczytać modułu wyświetlającego artykuły.",
      rendererFailedHint:
        "Być może Twoje połączenie zostało przerwane albo ExactDocs został zaktualizowany. Sam plik jest w porządku.",
      viewSource: "Pokaż źródło",
      sourceText: "Tekst źródłowy",
      largeFile: (kb) => `Ten plik ma ${formatNumber(kb, "pl")} kB, więc otwiera się jako źródło.`,
      renderAnyway: "Pokaż podgląd mimo to",
      movedFrom: (path, ref) => (
        <>
          Przeniesiono z {path} w {ref}
        </>
      ),
      articleText: "Treść artykułu",
      contents: "Spis treści",
      loading: (path) => `Wczytywanie ${path}`,
      loadFailed: "Nie udało się wczytać artykułu",
      noAnswer: "ExactDocs nie odpowiada. Sprawdź, czy działa, i spróbuj ponownie.",
      onThisPage: "Na tej stronie",
      sections: (count) => plural.pl(count, { one: "# sekcja", few: "# sekcje", many: "# sekcji" }),
    },
    tree: {
      files: "Pliki",
      browseFiles: "Przeglądaj pliki",
      filesOf: (ref) => `Pliki wersji ${ref}`,
      loadingFiles: "Wczytywanie plików",
      filesFailed: (ref) => `Nie udało się wczytać plików wersji ${ref}.`,
      noneTagged: (tags) => `Brak artykułów z tagiem ${tags.join(" lub ")}`,
      nothingHere: "Nic tu nie zaimportowano",
      noneWithTags: (ref, count) =>
        `W ${ref} nie ma artykułu z ${count > 1 ? "żadnym z tych tagów" : "tym tagiem"}.`,
      noArticles: (ref) => `W ${ref} nie ma artykułów. Import mógł pominąć wszystkie pliki.`,
      showAll: "Pokaż wszystkie artykuły",
      moreFailed: (folder) =>
        folder
          ? `Nie udało się wczytać folderu ${folder}. Spróbuj ponownie`
          : "Nie udało się wczytać kolejnych plików. Spróbuj ponownie",
      loadingMore: "Wczytywanie kolejnych",
      showMore: (folder) => (folder ? `Pokaż więcej w ${folder}` : "Pokaż więcej plików"),
      file: "Plik",
      loading: "Wczytywanie",
    },
    versions: {
      default: "domyślna",
      pinnedDefault: "przypięta domyślna",
      trigger: (ref) => `Wersja: ${ref}. Zmień wersję`,
      switching: (ref, to) => `Wersja: ${ref}, przełączanie na ${to}. Zmień wersję`,
      filterPlaceholder: (count) =>
        plural.pl(count, {
          one: "Filtruj # wersję",
          few: "Filtruj # wersje",
          many: "Filtruj # wersji",
        }),
      filter: "Filtruj wersje",
      list: "Wersje",
      kind: { branch: "gałąź", commit: "commit" },
      noMatch: (filter) => `Żadna wersja nie pasuje do „${filter}”.`,
      gone: "Ta wersja lub biblioteka nie jest już zaimportowana. Odśwież stronę.",
      signIn: "Zaloguj się ponownie, aby to zmienić.",
      changeFailed: "Nie udało się zmienić wersji domyślnej. Spróbuj ponownie.",
      setToast: "Ustawiono wersję domyślną",
      unpinnedToast: "Odpięto wersję domyślną",
      followsRule: "Znów obowiązuje reguła wyboru wersji domyślnej.",
      setTo: (ref) => `Ustawiono wersję domyślną: ${ref}.`,
      unpinned: "Odpięto wersję domyślną.",
      pinAs: (ref) => <>Przypnij {ref} jako domyślną</>,
      unpin: "Odepnij domyślną",
      backToAutomatic: "znów automatycznie",
    },
    tags: {
      invalid: (max) =>
        `Tag zaczyna się od litery lub cyfry, a dalej może zawierać litery, cyfry oraz . _ + - (najwyżej ${plural.pl(max, { one: "# znak", few: "# znaki", many: "# znaków" })}).`,
      duplicate: "Ten artykuł ma już ten tag.",
      tooMany: (max) =>
        `Do ścieżki artykułu można ręcznie dodać najwyżej ${plural.pl(max, { one: "# tag", few: "# tagi", many: "# tagów" })}.`,
      signIn: "Zaloguj się ponownie, aby zmienić tagi.",
      gone: "Ta biblioteka nie jest już zaimportowana. Odśwież stronę.",
      saveFailed: "Nie udało się zapisać tagów. Spróbuj ponownie.",
      setOn: (path) => <>przypisany do {path}</>,
      removeTag: (tag) => `Usuń tag ${tag}`,
      removeTagSetOn: (tag, path) => `Usuń tag ${tag}, przypisany do ${path}`,
      newTag: "Nowy tag",
      add: "Dodaj",
      hint: "Dla tej ścieżki we wszystkich wersjach biblioteki, także po późniejszej zmianie nazwy.",
      added: "Dodano tag",
      removed: "Usunięto tag",
      undo: "Cofnij",
      region: "Tagi",
      fromFile: "Z pliku",
      fromFrontMatter: "Tagi z front matter",
      fromRules: "Z reguł ścieżek",
      fromRulesList: "Tagi z reguł ścieżek",
      imported: "Zaimportowane",
      importedList: "Tagi z front matter lub reguł ścieżek",
      importedNote:
        "Tę wersję zaimportowano, zanim ExactDocs zaczął zapisywać pochodzenie tagów. Ponowny import albo zmiana reguły tagów pozwoli je rozróżnić.",
      addedHere: "Dodane tutaj",
      addedList: "Tagi dodane ręcznie",
      addTag: "Dodaj tag",
      kept: (tag) => `${tag} pozostaje przy tym artykule: nadaje go również import.`,
    },
    render: {
      pressCtrlC: "Naciśnij Ctrl+C",
      copyFailed: "Błąd kopiowania",
      code: "kod",
      file: "plik",
      plainText: "Tekst",
      noImage: (alt) => `Obraz niedostępny: ${alt || "Obraz"}`,
      linkTo: (heading) => `Link do nagłówka „${heading}”`,
      done: "Wykonane",
      notDone: "Niewykonane",
      table: (name) => (name ? `Tabela: ${name}` : "Tabela"),
      variant: {
        note: "Uwaga",
        tip: "Porada",
        warning: "Ostrzeżenie",
        danger: "Niebezpieczeństwo",
      },
    },
  },
);
