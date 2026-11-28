import { FileText, FolderTree, GitBranch, Search, Settings } from "lucide-react";
import type { HelpTopic } from "@/shared/ui/page-help";

/** A library page's tour. Targets are the `data-tour` values in browse-page.tsx and files-aside.tsx. */
export const libraryHelp: HelpTopic = {
  title: { en: "Reading a library", pl: "Jak czytać bibliotekę" },
  steps: [
    {
      icon: GitBranch,
      target: "library-version",
      title: { en: "Pick a version", pl: "Wybór wersji" },
      body: {
        en: "Every imported version is kept apart. The files, the search and the articles all follow the version picked here.",
        pl: "Każda zaimportowana wersja jest trzymana osobno. Pliki, wyszukiwanie i artykuły pokazują wersję wybraną tutaj.",
      },
      guide: "architecture/versions/",
    },
    {
      icon: Search,
      target: "library-search",
      title: { en: "Search this version", pl: "Szukanie w tej wersji" },
      body: {
        en: "Searches only this version; press / to jump here. A result opens its article at the matching section.",
        pl: "Przeszukuje tylko tę wersję; naciśnij /, aby tu przejść. Wynik otwiera artykuł w pasującej sekcji.",
      },
      guide: "search/",
    },
    {
      icon: FolderTree,
      target: "library-files",
      title: { en: "Tags and files", pl: "Tagi i pliki" },
      body: {
        en: "The tree lists the imported Markdown files. Tags narrow it to the articles that carry them.",
        pl: "Drzewo pokazuje zaimportowane pliki Markdown. Tagi zawężają je do artykułów, które je mają.",
      },
      guide: "search/chunks/",
    },
    {
      icon: FileText,
      target: "library-reader",
      title: { en: "Articles", pl: "Artykuły" },
      body: {
        en: "The version's articles, or the one you opened, with its commit and a link to the file on the git host.",
        pl: "Artykuły tej wersji albo ten, który otworzysz, z commitem i linkiem do pliku na serwerze git.",
      },
      guide: "architecture/versions/",
    },
    {
      icon: Settings,
      target: "library-settings",
      title: { en: "Settings and sharing", pl: "Ustawienia i udostępnianie" },
      body: {
        en: "Settings change the paths, versions, sync and AI of this library. Share gives other people a role on it.",
        pl: "Ustawienia zmieniają ścieżki, wersje, synchronizację i AI tej biblioteki. Udostępnij nadaje innym osobom rolę w niej.",
      },
      guide: "getting-started/accounts/#library-roles-and-sharing",
    },
  ],
};
