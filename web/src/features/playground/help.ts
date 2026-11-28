import { Columns2, LibraryBig, Search, SlidersHorizontal } from "lucide-react";
import type { HelpTopic } from "@/shared/ui/page-help";

/** The playground's tour. Targets are the `data-tour` values in playground-page.tsx. */
export const playgroundHelp: HelpTopic = {
  title: { en: "Using the playground", pl: "Jak korzystać z piaskownicy" },
  steps: [
    {
      icon: Search,
      target: "playground-query",
      title: { en: "The query", pl: "Zapytanie" },
      body: {
        en: "Write the question the way an agent would ask it: an API name, a config key or a task.",
        pl: "Wpisz pytanie tak, jak zadałby je agent: nazwę API, klucz konfiguracji albo zadanie.",
      },
      guide: "search/",
    },
    {
      icon: LibraryBig,
      target: "playground-libraries",
      title: { en: "Which libraries", pl: "Które biblioteki" },
      body: {
        en: "Choose one or more libraries, or leave it empty to search all of them at their default version.",
        pl: "Wybierz jedną lub więcej bibliotek albo zostaw puste, aby szukać we wszystkich w ich domyślnej wersji.",
      },
      guide: "search/",
    },
    {
      icon: SlidersHorizontal,
      target: "playground-mode",
      title: { en: "Retrieval mode", pl: "Tryb wyszukiwania" },
      body: {
        en: "BM25 matches words, vector search matches meaning, and hybrid fuses both. Agent answer lets an LLM read the docs and write a reply.",
        pl: "BM25 dopasowuje słowa, wyszukiwanie wektorowe znaczenie, a hybrydowe łączy oba. Odpowiedź agenta to LLM, który czyta dokumentację i pisze odpowiedź.",
      },
      guide: "search/#retrieval-modes",
    },
    {
      icon: Columns2,
      target: "playground-compare",
      title: { en: "Compare two modes", pl: "Porównanie dwóch trybów" },
      body: {
        en: "Run a second mode beside the first to see how their rankings differ. A mode that can't answer says which one answered instead.",
        pl: "Uruchom drugi tryb obok pierwszego, aby zobaczyć, czym różnią się ich rankingi. Tryb, który nie może odpowiedzieć, mówi, który odpowiedział zamiast niego.",
      },
      guide: "search/#which-mode-answers",
    },
  ],
};
