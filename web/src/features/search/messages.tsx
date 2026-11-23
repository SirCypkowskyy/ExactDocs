import type { ReactNode } from "react";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";

/*
 * The search slice's strings: the header box, a version's box and results, and the /search page.
 * The hits themselves (headings, paths, snippets) come from the libraries and stay as they are.
 */

/** "3 results" / "Top 20 results": the count as one phrase. */
const resultsEn = (n: number, complete: boolean) =>
  `${complete ? "" : "Top "}${plural.en(n, { one: "# result", other: "# results" })}`;

const resultsPl = (n: number, complete: boolean) =>
  complete
    ? plural.pl(n, { one: "# wynik", few: "# wyniki", many: "# wyników" })
    : plural.pl(n, {
        one: "# najlepszy wynik",
        few: "# najlepsze wyniki",
        many: "# najlepszych wyników",
      });

const quoteEn = (q: string) => `“${q}”`;
const quotePl = (q: string) => `„${q}”`;

export const messages = defineMessages(
  {
    box: {
      /** The global box's landmark. */
      allLibraries: "All libraries",
      searchAll: "Search all libraries",
      searchIn: (ref: string) => `Search ${ref}`,
    },
    tags: {
      label: "Tags",
      mustMatch: "Tags must match",
      matchAny: "Match any",
      matchAll: "Match all",
    },
    results: {
      heading: "Search results",
      quote: quoteEn,
      count: resultsEn,
      /** "3 results", "Showing 3 of 5", "Top 20 of 87": the visible count next to the facet totals. */
      countLine: (shown: number, total: number, complete: boolean) =>
        total <= shown
          ? resultsEn(shown, complete)
          : `${complete ? "Showing" : "Top"} ${formatNumber(shown, "en")} of ${formatNumber(total, "en")}`,
      inLibraries: (n: number) => `in ${plural.en(n, { one: "# library", other: "# libraries" })}`,
      inRef: (ref: ReactNode) => <>&nbsp;in&nbsp;{ref}</>,
      moveHint: (key: ReactNode) => <>{key} to move through results</>,
      bestOfVersion: (n: number) =>
        `Showing the best ${formatNumber(n, "en")}. More sections match: add a tag or a more specific word.`,
      bestOfAll: (n: number, narrowed: boolean) =>
        `Showing the best ${formatNumber(n, "en")}. More sections match: ${narrowed ? "use a more specific word." : "use a library above or a more specific word."}`,
      omitted: (searched: number, all: number, omitted: number, link: ReactNode) => (
        <>
          Searched {formatNumber(searched, "en")} of {formatNumber(all, "en")} libraries; the other{" "}
          {formatNumber(omitted, "en")} are not searched here. {link}.
        </>
      ),
      browseLink: "Browse them on the Libraries page",
      version: "version ",
      commit: "commit ",
    },
    /** The one sentence the live region announces once a result set settles. */
    status: {
      all: (n: number, q: string, library: string | undefined, complete: boolean) =>
        `${n === 0 ? "No results" : resultsEn(n, complete)} for ${quoteEn(q)} ${library ? `in ${library}` : "in all libraries"}`,
      version: (n: number, q: string, ref: string, complete: boolean) =>
        n === 0
          ? `No results for ${quoteEn(q)} in ${ref}`
          : `${resultsEn(n, complete)} for ${quoteEn(q)} in ${ref}`,
    },
    facets: {
      label: "Libraries with matches",
      all: "All libraries",
      allLabel: (n: number) =>
        `All libraries, ${plural.en(n, { one: "# match", other: "# matches" })}`,
      library: (library: string, n: number) =>
        `${library}, ${plural.en(n, { one: "# match", other: "# matches" })}`,
      more: (n: number) => `+${plural.en(n, { one: "# more library", other: "# more libraries" })}`,
    },
    empty: {
      noResults: "No results",
      noResultsIn: (where: string) => `No results in ${where}`,
      unavailableTitle: "Library not available",
      unavailable: (library: ReactNode) => (
        <>{library} can't be searched: it was removed, or it has no imported version.</>
      ),
      nothing: (q: ReactNode, narrowed: boolean) => (
        <>
          Nothing {narrowed ? "there" : "in any library's default version"} matches {q}. Try fewer
          or different words, or check the spelling.
          {!narrowed && " To search another version, open the library and use its search box."}
        </>
      ),
      nothingIn: (ref: ReactNode, q: ReactNode, tags: readonly string[], all: boolean) => (
        <>
          Nothing in {ref} matches {q}
          {tags.length > 0 && ` among articles tagged ${tags.join(all ? " and " : " or ")}`}. Try
          fewer or different words.
        </>
      ),
      removeTagFilter: "Remove tag filter",
      searchInstead: (ref: ReactNode) => <>Search&nbsp;{ref}&nbsp;instead</>,
    },
    prompt: {
      title: "Search every library at once",
      body: (first: ReactNode, second: ReactNode) => (
        <>
          Type an API name, a config key or an error message, for example {first} or {second}.
          Results come from each library's default version, with its commit.
        </>
      ),
      slash: (key: ReactNode) => <>Press {key} from any page to start typing.</>,
    },
    failed: {
      title: "Search failed",
      all: "Couldn't search. Check your connection or try again.",
      version: (ref: string) => `Couldn't search ${ref}. Check your connection or try again.`,
    },
    page: {
      title: (q: ReactNode) => <>Search: {q}</>,
      description: "Searches the default version of every library.",
    },
  },
  {
    box: {
      allLibraries: "Wszystkie biblioteki",
      searchAll: "Szukaj we wszystkich bibliotekach",
      searchIn: (ref) => `Szukaj w ${ref}`,
    },
    tags: {
      label: "Tagi",
      mustMatch: "Dopasowanie tagów",
      matchAny: "Dowolny tag",
      matchAll: "Wszystkie tagi",
    },
    results: {
      heading: "Wyniki wyszukiwania",
      quote: quotePl,
      count: resultsPl,
      countLine: (shown, total, complete) =>
        total <= shown
          ? resultsPl(shown, complete)
          : complete
            ? `Pokazano ${formatNumber(shown, "pl")} z ${formatNumber(total, "pl")}`
            : `${plural.pl(shown, { one: "# najlepszy", few: "# najlepsze", many: "# najlepszych" })} z ${formatNumber(total, "pl")}`,
      inLibraries: (n) =>
        `w ${plural.pl(n, { one: "# bibliotece", few: "# bibliotekach", many: "# bibliotekach" })}`,
      inRef: (ref) => <>&nbsp;w&nbsp;{ref}</>,
      moveHint: (key) => <>{key} – przeglądaj wyniki</>,
      bestOfVersion: (n) =>
        `Pokazano ${plural.pl(n, { one: "# najlepszy wynik", few: "# najlepsze wyniki", many: "# najlepszych wyników" })}. Pasuje więcej fragmentów: dodaj tag lub bardziej szczegółowe słowo.`,
      bestOfAll: (n, narrowed) =>
        `Pokazano ${plural.pl(n, { one: "# najlepszy wynik", few: "# najlepsze wyniki", many: "# najlepszych wyników" })}. Pasuje więcej fragmentów: ${narrowed ? "użyj bardziej szczegółowego słowa." : "wybierz bibliotekę powyżej lub użyj bardziej szczegółowego słowa."}`,
      omitted: (searched, all, omitted, link) => (
        <>
          {`Przeszukano ${formatNumber(searched, "pl")} z ${plural.pl(all, { one: "# biblioteki", few: "# bibliotek", many: "# bibliotek" })}; pozostałych ${formatNumber(omitted, "pl")} tutaj się nie przeszukuje.`}{" "}
          {link}.
        </>
      ),
      browseLink: "Przejrzyj je na stronie Biblioteki",
      version: "wersja ",
      commit: "commit ",
    },
    status: {
      all: (n, q, library, complete) =>
        `${n === 0 ? "Brak wyników" : resultsPl(n, complete)} dla ${quotePl(q)} ${library ? `w ${library}` : "we wszystkich bibliotekach"}`,
      version: (n, q, ref, complete) =>
        n === 0
          ? `Brak wyników dla ${quotePl(q)} w ${ref}`
          : `${resultsPl(n, complete)} dla ${quotePl(q)} w ${ref}`,
    },
    facets: {
      label: "Biblioteki z trafieniami",
      all: "Wszystkie biblioteki",
      allLabel: (n) =>
        `Wszystkie biblioteki, ${plural.pl(n, { one: "# trafienie", few: "# trafienia", many: "# trafień" })}`,
      library: (library, n) =>
        `${library}, ${plural.pl(n, { one: "# trafienie", few: "# trafienia", many: "# trafień" })}`,
      more: (n) =>
        `+${plural.pl(n, { one: "# kolejna biblioteka", few: "# kolejne biblioteki", many: "# kolejnych bibliotek" })}`,
    },
    empty: {
      noResults: "Brak wyników",
      noResultsIn: (where) => `Brak wyników w ${where}`,
      unavailableTitle: "Biblioteka niedostępna",
      unavailable: (library) => (
        <>
          Nie można przeszukać {library}: biblioteka została usunięta albo nie ma żadnej
          zaimportowanej wersji.
        </>
      ),
      nothing: (q, narrowed) => (
        <>
          {narrowed ? "Nic tam nie pasuje" : "Nic w domyślnej wersji żadnej biblioteki nie pasuje"}{" "}
          do {q}. Wpisz mniej słów lub inne albo sprawdź pisownię.
          {!narrowed &&
            " Aby przeszukać inną wersję, otwórz bibliotekę i użyj jej pola wyszukiwania."}
        </>
      ),
      nothingIn: (ref, q, tags, all) => (
        <>
          W {ref} nic nie pasuje do {q}
          {tags.length > 0 &&
            (all
              ? ` wśród artykułów z tagami ${tags.join(" i ")}`
              : ` wśród artykułów z tagiem ${tags.join(" lub ")}`)}
          . Wpisz mniej słów lub inne.
        </>
      ),
      removeTagFilter: "Usuń filtr tagów",
      searchInstead: (ref) => <>Zamiast tego szukaj w&nbsp;{ref}</>,
    },
    prompt: {
      title: "Przeszukaj wszystkie biblioteki naraz",
      body: (first, second) => (
        <>
          Wpisz nazwę API, klucz konfiguracji lub komunikat błędu, na przykład {first} lub {second}.
          Wyniki pochodzą z domyślnej wersji każdej biblioteki, wraz z jej commitem.
        </>
      ),
      slash: (key) => <>Naciśnij {key} na dowolnej stronie, aby zacząć pisać.</>,
    },
    failed: {
      title: "Wyszukiwanie nie powiodło się",
      all: "Nie udało się wyszukać. Sprawdź połączenie lub spróbuj ponownie.",
      version: (ref) => `Nie udało się przeszukać ${ref}. Sprawdź połączenie lub spróbuj ponownie.`,
    },
    page: {
      title: (q) => <>Wyszukiwanie: {q}</>,
      description: "Przeszukuje domyślną wersję każdej biblioteki.",
    },
  },
);
