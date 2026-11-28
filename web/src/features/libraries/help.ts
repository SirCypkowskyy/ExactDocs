import { Activity, Ban, CircleX, Ellipsis, LibraryBig, ListFilter, Plus } from "lucide-react";
import type { HelpTopic } from "@/shared/ui/page-help";

/** The libraries page's tour. Targets are the `data-tour` values in libraries-page.tsx. */
export const librariesHelp: HelpTopic = {
  title: { en: "Using the library list", pl: "Jak korzystać z listy bibliotek" },
  steps: [
    {
      icon: LibraryBig,
      target: "libraries-table",
      title: { en: "Your libraries", pl: "Twoje biblioteki" },
      body: {
        en: "Each row is a git repository imported as a library, with its default version, its versions and articles, and its last sync. Open one to read it.",
        pl: "Każdy wiersz to repozytorium git zaimportowane jako biblioteka: jego domyślna wersja, wersje, artykuły i ostatnia synchronizacja. Otwórz ją, aby czytać.",
      },
      guide: "getting-started/#add-your-first-library",
    },
    {
      icon: ListFilter,
      target: "libraries-toolbar",
      title: { en: "Find and filter", pl: "Szukanie i filtry" },
      body: {
        en: "Find a library by name, ID or description, and narrow the list by sync state, AI or versions. The view stays in the address, so a link keeps it.",
        pl: "Znajdź bibliotekę po nazwie, ID lub opisie i zawęź listę według stanu synchronizacji, AI lub wersji. Widok zostaje w adresie, więc link go zachowuje.",
      },
      guide: "getting-started/#add-your-first-library",
    },
    {
      icon: Ellipsis,
      target: "libraries-table",
      title: { en: "Row actions", pl: "Akcje wiersza" },
      body: {
        en: "The menu at the end of a row, or a right-click, opens settings and sharing, syncs a branch version now, or shows the library's jobs.",
        pl: "Menu na końcu wiersza (albo prawy przycisk myszy) otwiera ustawienia i udostępnianie, od razu synchronizuje wersję z gałęzi albo pokazuje zadania biblioteki.",
      },
      guide: "getting-started/sync/#keep-branch-versions-fresh",
    },
    {
      icon: Plus,
      target: "add-library",
      title: { en: "Add a library", pl: "Dodawanie biblioteki" },
      body: {
        en: "Give a repository address, pick the version and the paths to import. The import runs as a job you can follow on the Jobs page.",
        pl: "Podaj adres repozytorium, wybierz wersję i ścieżki do zaimportowania. Import działa jako zadanie, które śledzisz na stronie Zadania.",
      },
      guide: "getting-started/#add-your-first-library",
    },
  ],
};

/** The jobs page's tour. Targets are the `data-tour` values in jobs-page.tsx. */
export const jobsHelp: HelpTopic = {
  title: { en: "Reading the jobs", pl: "Jak czytać zadania" },
  steps: [
    {
      icon: Activity,
      target: "jobs-table",
      title: { en: "Background work", pl: "Praca w tle" },
      body: {
        en: "Imports, syncs, embeddings and the other background jobs, newest first, with their state, progress and who started them.",
        pl: "Importy, synchronizacje, embeddingi i inne zadania w tle, od najnowszych, z ich stanem, postępem i tym, kto je uruchomił.",
      },
      guide: "rest-api/jobs/#a-job",
    },
    {
      icon: ListFilter,
      target: "jobs-toolbar",
      title: { en: "Narrow the list", pl: "Zawężanie listy" },
      body: {
        en: "Find a job by library, version or error, or filter by state, kind or one library.",
        pl: "Znajdź zadanie po bibliotece, wersji lub błędzie albo filtruj według stanu, rodzaju lub jednej biblioteki.",
      },
      guide: "rest-api/jobs/#the-newest-jobs",
    },
    {
      icon: CircleX,
      target: "jobs-table",
      title: { en: "When a job fails", pl: "Gdy zadanie się nie uda" },
      body: {
        en: "A failed job shows its error code; point at it or focus it to read why it failed.",
        pl: "Nieudane zadanie pokazuje kod błędu; wskaż go lub ustaw na nim fokus, aby przeczytać przyczynę.",
      },
      guide: "rest-api/jobs/#failures",
    },
    {
      icon: Ban,
      target: "jobs-table",
      title: { en: "Cancel a job", pl: "Anulowanie zadania" },
      body: {
        en: "A queued or running job can be cancelled from its row's menu. A running import stops without publishing half a version.",
        pl: "Zadanie w kolejce lub w toku można anulować z menu jego wiersza. Przerwany import nie publikuje połowy wersji.",
      },
      guide: "rest-api/jobs/#cancelling-a-job",
    },
  ],
};
