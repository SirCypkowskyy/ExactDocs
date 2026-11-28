import { LibraryBig, ListOrdered, Search } from "lucide-react";
import type { HelpTopic } from "@/shared/ui/page-help";

/** The search page's tour. Targets are the `data-tour` values in global-search-page.tsx. */
export const searchHelp: HelpTopic = {
  title: { en: "Searching every library", pl: "Jak szukać we wszystkich bibliotekach" },
  steps: [
    {
      icon: Search,
      target: "search-box",
      title: { en: "One box for all", pl: "Jedno pole dla wszystkich" },
      body: {
        en: "Searches the default version of every library you can read. Try an API name, a config key or an error message.",
        pl: "Przeszukuje domyślną wersję każdej biblioteki, którą możesz czytać. Wpisz nazwę API, klucz konfiguracji albo komunikat błędu.",
      },
      guide: "search/",
    },
    {
      icon: LibraryBig,
      target: "search-facets",
      title: { en: "Matches per library", pl: "Trafienia w bibliotekach" },
      body: {
        en: "How many matches each library has. Pick one to see only its results.",
        pl: "Ile trafień ma każda biblioteka. Wybierz jedną, aby zobaczyć tylko jej wyniki.",
      },
      guide: "search/",
    },
    {
      icon: ListOrdered,
      target: "search-results",
      title: { en: "Results", pl: "Wyniki" },
      body: {
        en: "Each hit names its library, version, path and commit. Open one to land on the matching section of the article.",
        pl: "Każde trafienie podaje bibliotekę, wersję, ścieżkę i commit. Otwórz je, aby trafić do pasującej sekcji artykułu.",
      },
      guide: "search/#retrieval-modes",
    },
  ],
};
