import type { ReactNode } from "react";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";

type SortDirection = false | "asc" | "desc";

/** What a progress count counts. */
type ProgressUnit = "files" | "chunks" | "versions" | "steps";

/** Strings of the shared components (tables, credential and path fields, the ref picker, toasts). */
export const messages = defineMessages(
  {
    table: {
      sortBy: (column: string, dir: SortDirection) =>
        `Sort by ${column}${dir ? `, sorted ${dir === "asc" ? "ascending" : "descending"}` : ""}`,
      columns: "Columns",
      showColumns: "Show columns",
      showing: (shown: number, total: number) => `Showing ${shown} of ${total}`,
      loadMore: "Load more",
    },
    /** DataTable v2: pagination, toolbar, row actions, states and cells. */
    dataTable: {
      pagination: "Pagination",
      range: (from: number, to: number, total: number) =>
        `${formatNumber(from, "en")}–${formatNumber(to, "en")} of ${formatNumber(total, "en")}`,
      rowsPerPage: "Rows per page",
      pageOf: (page: number, count: number) =>
        `Page ${formatNumber(page, "en")} of ${formatNumber(count, "en")}`,
      firstPage: "First page",
      previousPage: "Previous page",
      nextPage: "Next page",
      lastPage: "Last page",
      page: (page: number) => `Page ${formatNumber(page, "en")}`,
      outOfReach: (what: string, last: number) =>
        `${what} (out of reach: jumps stop at page ${formatNumber(last, "en")}; go on with Next page)`,
      jumpsStop: (last: number) =>
        `Jumps stop at page ${formatNumber(last, "en")}; later pages open with Next page.`,
      filters: "Filters",
      activeFilters: "Active filters",
      filterSelected: (title: string, n: number) =>
        n ? `${title}, ${formatNumber(n, "en")} selected` : title,
      filterOptions: (title: string) => `Filter the ${title.toLowerCase()} options`,
      chip: (title: string, value: string) => `${title}: ${value}`,
      removeFilter: (chip: string) => `Remove filter ${chip}`,
      clearFacet: "Clear",
      clearAll: "Clear all",
      clearFilters: "Clear filters",
      noOptions: "No matches",
      search: "Search",
      moreActions: (row: string) => `More actions for ${row}`,
      actions: "Actions",
      empty: "Nothing here yet.",
      noMatchTitle: "Nothing matches",
      noMatch: "Nothing matches these filters.",
      loadFailed: "Couldn't load this list.",
      loading: "Loading",
      busy: "Updating",
      copy: (what: string) => `Copy ${what}`,
      copied: (what: string) => `Copied ${what}.`,
      progress: (done: number, total: number, unit: ProgressUnit) =>
        `${formatNumber(done, "en")} / ${plural.en(total, {
          one: `# ${unit.slice(0, -1)}`,
          other: `# ${unit}`,
        })}`,
      progressLabel: (what: string) => `Progress of ${what}`,
      pending: "Not started",
    },
    confirm: {
      typeToConfirm: (phrase: ReactNode): ReactNode => <>Type {phrase} to confirm</>,
      working: "Working…",
    },
    breadcrumb: {
      label: "Breadcrumb",
      more: "More",
    },
    command: {
      empty: "No results.",
    },
    /** The library combobox (Playground, token scope, the jobs and access-log filters, search). */
    libraryPicker: {
      choose: "Choose a library…",
      find: "Find a library",
      findPlaceholder: "Find a library…",
      recent: "Recent",
      all: "All libraries",
      loading: "Loading libraries",
      failed: "Couldn't load the libraries.",
      none: "No libraries yet.",
      noMatch: (text: string) => `No library matches “${text}”.`,
      found: (n: number) => plural.en(n, { one: "# library", other: "# libraries" }),
      partial: (shown: number, total: number) =>
        `Showing ${formatNumber(shown, "en")} of ${formatNumber(total, "en")}. Type to narrow the list.`,
      typedChoice: (id: ReactNode): ReactNode => <>Use {id}</>,
      selected: (n: number) =>
        plural.en(n, { one: "# library chosen", other: "# libraries chosen" }),
      chosen: "Chosen libraries",
      remove: (id: string) => `Remove ${id}`,
      clear: "Clear",
    },
    credential: {
      fileTooBig: "That file is too big to be a deploy key.",
      token: "Access token",
      key: "Deploy key",
      pasteToken: "Paste the token",
      pasteKey: "Paste the private key",
      tokenHint:
        "A token that can read this repository. It is stored encrypted and never shown again.",
      keyHint:
        "The private half of a deploy key without a passphrase. Paste it or choose its file. It is stored encrypted and never shown again.",
      username: "User name (optional)",
      usernameHint:
        "Leave it empty for GitHub and GitLab. Bitbucket repository tokens use x-token-auth.",
      chooseFile: "Choose key file",
      keyRead: (file: string) => `Key read from ${file}.`,
    },
    paths: {
      include: "Only these paths",
      exclude: "Leave out",
      hint: (folder: ReactNode, glob: ReactNode): ReactNode => (
        <>
          One per line, relative to the repository root: a folder ({folder}), a file or a glob (
          {glob}). Empty means every Markdown and reStructuredText (.rst) file. A .txt file needs a
          path that names .txt. Leaving a path out always wins.
        </>
      ),
    },
    rules: {
      legend: "Tags by path",
      hint: "Give articles a tag by where they live, so agents can filter by it. Added to the tags in each article's front matter.",
      full: (max: number) => ` You can have up to ${max} rules.`,
      path: "Path",
      tag: "Tag",
      pathFor: (n: number) => `Path for tag rule ${n}`,
      tagFor: (n: number) => `Tag for rule ${n}`,
      remove: (n: number) => `Remove tag rule ${n}`,
      add: "Add a tag rule",
    },
    refs: {
      filter: "Filter branches and tags",
      matches: (found: number, of: number) => `${found} of ${of} match`,
      choose: "Choose a branch or tag…",
      defaultBranch: (name: string | null | undefined) =>
        `Default branch${name ? ` (${name})` : ""}`,
      branches: (n: number) => `Branches (${n})`,
      tags: (n: number) => `Tags (${n})`,
      another: "Another ref or commit…",
      noMatch: (query: string) =>
        `Nothing matches “${query}”. Pick “Another ref or commit…” to type it.`,
      unavailable:
        "Couldn't load branches and tags. Type a version below, or leave it empty for the default branch.",
      label: "Version to import",
      loading: "Loading branches and tags",
      typedPlaceholder: "v1.4.0, release/2, or a commit SHA",
      typedLabel: "Branch, tag or commit",
      truncated:
        "Only the first 1000 branches and 1000 tags are listed. Pick “Another ref or commit…” for the rest.",
      pinned: "The version is pinned to the commit it points to today, so the docs stay exact.",
    },
    tags: {
      filter: "Filter by tag",
      count: (n: number) => String(n),
      truncated: "Showing the most used tags only.",
    },
    toasts: {
      region: "Notifications",
      close: "Close toast",
    },
  },
  {
    table: {
      sortBy: (column, dir) =>
        `Sortuj według: ${column}${dir ? `, sortowanie ${dir === "asc" ? "rosnące" : "malejące"}` : ""}`,
      columns: "Kolumny",
      showColumns: "Pokaż kolumny",
      showing: (shown, total) =>
        `Wyświetlono ${formatNumber(shown, "pl")} z ${formatNumber(total, "pl")}`,
      loadMore: "Wczytaj więcej",
    },
    dataTable: {
      pagination: "Stronicowanie",
      range: (from, to, total) =>
        `${formatNumber(from, "pl")}–${formatNumber(to, "pl")} z ${formatNumber(total, "pl")}`,
      rowsPerPage: "Wierszy na stronie",
      pageOf: (page, count) => `Strona ${formatNumber(page, "pl")} z ${formatNumber(count, "pl")}`,
      firstPage: "Pierwsza strona",
      previousPage: "Poprzednia strona",
      nextPage: "Następna strona",
      lastPage: "Ostatnia strona",
      page: (page) => `Strona ${formatNumber(page, "pl")}`,
      outOfReach: (what, last) =>
        `${what} (poza zasięgiem: skoki kończą się na stronie ${formatNumber(last, "pl")}; dalej przejdź przyciskiem „Następna strona”)`,
      jumpsStop: (last) =>
        `Skoki kończą się na stronie ${formatNumber(last, "pl")}; dalsze strony otwiera przycisk „Następna strona”.`,
      filters: "Filtry",
      activeFilters: "Aktywne filtry",
      filterSelected: (title, n) => (n ? `${title}, wybrano: ${formatNumber(n, "pl")}` : title),
      filterOptions: (title) => `Filtruj opcje: ${title.toLowerCase()}`,
      chip: (title, value) => `${title}: ${value}`,
      removeFilter: (chip) => `Usuń filtr ${chip}`,
      clearFacet: "Wyczyść",
      clearAll: "Wyczyść wszystko",
      clearFilters: "Wyczyść filtry",
      noOptions: "Brak dopasowań",
      search: "Szukaj",
      moreActions: (row) => `Więcej opcji: ${row}`,
      actions: "Akcje",
      empty: "Nic tu jeszcze nie ma.",
      noMatchTitle: "Nic nie pasuje",
      noMatch: "Nic nie pasuje do tych filtrów.",
      loadFailed: "Nie udało się wczytać tej listy.",
      loading: "Wczytywanie",
      busy: "Odświeżanie",
      copy: (what) => `Kopiuj: ${what}`,
      copied: (what) => `Skopiowano: ${what}.`,
      progress: (done, total, unit) => {
        const forms = {
          files: { one: "# pliku", few: "# plików", many: "# plików" },
          chunks: { one: "# fragmentu", few: "# fragmentów", many: "# fragmentów" },
          versions: { one: "# wersji", few: "# wersji", many: "# wersji" },
          steps: { one: "# kroku", few: "# kroków", many: "# kroków" },
        }[unit];
        return `${formatNumber(done, "pl")} / ${plural.pl(total, forms)}`;
      },
      progressLabel: (what) => `Postęp: ${what}`,
      pending: "Nie rozpoczęto",
    },
    confirm: {
      typeToConfirm: (phrase) => <>Wpisz {phrase}, aby potwierdzić</>,
      working: "Trwa…",
    },
    breadcrumb: {
      label: "Ścieżka nawigacji",
      more: "Więcej",
    },
    command: {
      empty: "Brak wyników.",
    },
    libraryPicker: {
      choose: "Wybierz bibliotekę…",
      find: "Znajdź bibliotekę",
      findPlaceholder: "Znajdź bibliotekę…",
      recent: "Ostatnio używane",
      all: "Wszystkie biblioteki",
      loading: "Wczytywanie bibliotek",
      failed: "Nie udało się wczytać bibliotek.",
      none: "Nie ma jeszcze żadnych bibliotek.",
      noMatch: (text) => `Żadna biblioteka nie pasuje do „${text}”.`,
      found: (n) => plural.pl(n, { one: "# biblioteka", few: "# biblioteki", many: "# bibliotek" }),
      partial: (shown, total) =>
        `Widoczne: ${formatNumber(shown, "pl")} z ${formatNumber(total, "pl")}. Wpisz nazwę, aby zawęzić listę.`,
      typedChoice: (id) => <>Użyj {id}</>,
      selected: (n) =>
        `Wybrano ${plural.pl(n, { one: "# bibliotekę", few: "# biblioteki", many: "# bibliotek" })}`,
      chosen: "Wybrane biblioteki",
      remove: (id) => `Usuń ${id}`,
      clear: "Wyczyść",
    },
    credential: {
      fileTooBig: "Ten plik jest za duży, aby mógł być kluczem wdrożeniowym.",
      token: "Token dostępu",
      key: "Klucz wdrożeniowy",
      pasteToken: "Wklej token",
      pasteKey: "Wklej klucz prywatny",
      tokenHint:
        "Token z prawem odczytu tego repozytorium. Jest przechowywany w postaci zaszyfrowanej i nie zostanie już nigdy pokazany.",
      keyHint:
        "Prywatna część klucza wdrożeniowego bez hasła. Wklej ją lub wybierz plik z kluczem. Jest przechowywana w postaci zaszyfrowanej i nie zostanie już nigdy pokazana.",
      username: "Nazwa użytkownika (opcjonalnie)",
      usernameHint:
        "W przypadku GitHuba i GitLaba zostaw puste. Tokeny repozytoriów Bitbucket używają x-token-auth.",
      chooseFile: "Wybierz plik klucza",
      keyRead: (file) => `Wczytano klucz z pliku ${file}.`,
    },
    paths: {
      include: "Tylko te ścieżki",
      exclude: "Pomiń",
      hint: (folder, glob) => (
        <>
          Jedna na wiersz, względem katalogu głównego repozytorium: folder ({folder}), plik lub
          wzorzec glob ({glob}). Puste pole oznacza wszystkie pliki Markdown i reStructuredText
          (.rst). Plik .txt wymaga ścieżki, która wprost wskazuje .txt. Pominięcie ścieżki ma zawsze
          pierwszeństwo.
        </>
      ),
    },
    rules: {
      legend: "Tagi według ścieżki",
      hint: "Nadaj artykułom tag zależnie od tego, gdzie leżą, aby agenci mogli według niego filtrować. Dodawany do tagów z front matter każdego artykułu.",
      full: (max) =>
        ` Możesz mieć najwyżej ${plural.pl(max, { one: "# regułę", few: "# reguły", many: "# reguł" })}.`,
      path: "Ścieżka",
      tag: "Tag",
      pathFor: (n) => `Ścieżka reguły tagu ${n}`,
      tagFor: (n) => `Tag reguły ${n}`,
      remove: (n) => `Usuń regułę tagu ${n}`,
      add: "Dodaj regułę tagu",
    },
    refs: {
      filter: "Filtruj gałęzie i tagi",
      matches: (found, of) => `Pasuje: ${formatNumber(found, "pl")} z ${formatNumber(of, "pl")}`,
      choose: "Wybierz gałąź lub tag…",
      defaultBranch: (name) => `Domyślna gałąź${name ? ` (${name})` : ""}`,
      branches: (n) => `Gałęzie (${formatNumber(n, "pl")})`,
      tags: (n) => `Tagi (${formatNumber(n, "pl")})`,
      another: "Inny ref lub commit…",
      noMatch: (query) =>
        `Nic nie pasuje do „${query}”. Wybierz „Inny ref lub commit…”, aby go wpisać.`,
      unavailable:
        "Nie udało się wczytać gałęzi i tagów. Wpisz wersję poniżej albo zostaw puste pole, aby użyć domyślnej gałęzi.",
      label: "Wersja do zaimportowania",
      loading: "Wczytywanie gałęzi i tagów",
      typedPlaceholder: "v1.4.0, release/2 lub SHA commita",
      typedLabel: "Gałąź, tag lub commit",
      truncated:
        "Na liście jest tylko pierwszych 1000 gałęzi i 1000 tagów. Pozostałe wpisz po wybraniu „Inny ref lub commit…”.",
      pinned:
        "Wersja zostaje przypięta do commita, na który dziś wskazuje, więc dokumentacja pozostaje dokładna.",
    },
    tags: {
      filter: "Filtruj według tagu",
      count: (n) => formatNumber(n, "pl"),
      truncated: "Widoczne są tylko najczęściej używane tagi.",
    },
    toasts: {
      region: "Powiadomienia",
      close: "Zamknij powiadomienie",
    },
  },
);
