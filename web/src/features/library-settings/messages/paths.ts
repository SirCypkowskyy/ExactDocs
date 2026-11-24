import { defineMessages, formatNumber } from "@/shared/lib/i18n";

/** The Files and tags section, and the warning before every version is re-processed. */
export const pathsMessages = defineMessages(
  {
    description:
      "Which files of the repository become articles, and the tags they get by path. Saving a change re-processes every version.",
    privatePreview:
      "Preview isn't available for a private repository yet: it can't use the library's stored credential. Saving still re-processes every version with it.",
    save: "Save paths and tags",
    savedToast: "Saved files and tags",
    /** The label of the job line that re-processes the whole library. */
    everyVersion: "every version",
    lastFailed: {
      retag: "The last re-tagging failed. Every version keeps what it served.",
      rechunk: "The last re-chunking failed. Every version keeps what it served.",
      reprocess: "The last re-processing failed. Every version keeps what it served.",
    },
    runAgain: "Run again",
    /** Read after “Run again” by screen readers. */
    runAgainWhat: {
      retag: " the re-tagging with the saved paths and tag rules",
      rechunk: " the re-chunking with the saved paths and tag rules",
      reprocess: " the re-processing with the saved paths and tag rules",
    },
    warning: {
      /** `list`: the version, as listed. */
      one: {
        paths: (list: string) => `Its version (${list}) will be re-processed`,
        chunking: (list: string) => `Its version (${list}) will be re-chunked`,
        tags: (list: string) => `Its version (${list}) will be re-tagged`,
      },
      /** `list`: the first versions, and how many more. */
      every: {
        paths: (count: number, list: string) =>
          `Every version will be re-processed: all ${count} of them (${list})`,
        chunking: (count: number, list: string) =>
          `Every version will be re-chunked: all ${count} of them (${list})`,
        tags: (count: number, list: string) =>
          `Every version will be re-tagged: all ${count} of them (${list})`,
      },
      /** `which`: the sentence `one` or `every` made. */
      tags: (which: string) =>
        `${which}. Only the tag rules changed, so each one's articles are tagged again from what is stored, and nothing is fetched. Tags added by hand stay.`,
      chunking: (which: string) =>
        `${which}. The last re-chunking failed, so this runs it again: each one's stored articles are cut into chunks and tagged again, and nothing is fetched.`,
      pathsAfterFailure: (which: string) =>
        `${which}. The last re-processing failed, so this runs it in full: each version is fetched again at the commit it serves and imported with these paths and tag rules; branches are not synced.`,
      paths: (which: string) =>
        `${which}. Each one is fetched again at the commit it serves and imported with the new paths; branches are not synced.`,
      title: {
        paths: "Re-process every version?",
        chunking: "Re-chunk every version?",
        tags: "Re-tag every version?",
      },
      safe: "Each version keeps serving what it has now until its new state is complete, then switches at once. A version that cannot be re-processed keeps what it had.",
      confirm: {
        paths: "Save and re-process",
        chunking: "Save and re-chunk",
        tags: "Save and re-tag",
      },
    },
    headline: {
      noVersion:
        "Saved. The library has no version yet: versions imported from now on use these settings.",
      unchanged: "Saved. Nothing changed, so nothing is re-processed.",
      tags: "Saved. Every version is being re-tagged.",
      chunking: "Saved. Every version is being re-chunked.",
      paths: "Saved. Every version is being re-processed.",
    },
    hint: {
      unchanged: "Nothing changed yet.",
      noVersion: "No version is imported yet, so nothing is re-processed.",
      confirm: "You'll be asked to confirm: every version is re-processed.",
    },
  },
  {
    description:
      "Które pliki repozytorium stają się artykułami i jakie tagi dostają na podstawie ścieżki. Zapisanie zmiany przetwarza ponownie każdą wersję.",
    privatePreview:
      "Podgląd nie jest jeszcze dostępny dla prywatnego repozytorium: nie może korzystać z zapisanych danych uwierzytelniających biblioteki. Zapisanie i tak przetworzy ponownie każdą wersję z ich użyciem.",
    save: "Zapisz ścieżki i tagi",
    savedToast: "Zapisano pliki i tagi",
    everyVersion: "wszystkie wersje",
    lastFailed: {
      retag:
        "Ostatnie ponowne tagowanie nie powiodło się. Każda wersja nadal udostępnia to, co dotąd.",
      rechunk:
        "Ostatni ponowny podział na fragmenty nie powiódł się. Każda wersja nadal udostępnia to, co dotąd.",
      reprocess:
        "Ostatnie ponowne przetwarzanie nie powiodło się. Każda wersja nadal udostępnia to, co dotąd.",
    },
    runAgain: "Uruchom ponownie",
    runAgainWhat: {
      retag: " tagowanie z zapisanymi ścieżkami i regułami tagów",
      rechunk: " podział na fragmenty z zapisanymi ścieżkami i regułami tagów",
      reprocess: " przetwarzanie z zapisanymi ścieżkami i regułami tagów",
    },
    warning: {
      one: {
        paths: (list) => `Jej wersja (${list}) zostanie ponownie przetworzona`,
        chunking: (list) => `Jej wersja (${list}) zostanie ponownie podzielona na fragmenty`,
        tags: (list) => `Jej wersja (${list}) zostanie ponownie otagowana`,
      },
      every: {
        paths: (count, list) =>
          `Każda wersja zostanie ponownie przetworzona, łącznie ${formatNumber(count, "pl")} (${list})`,
        chunking: (count, list) =>
          `Każda wersja zostanie ponownie podzielona na fragmenty, łącznie ${formatNumber(count, "pl")} (${list})`,
        tags: (count, list) =>
          `Każda wersja zostanie ponownie otagowana, łącznie ${formatNumber(count, "pl")} (${list})`,
      },
      tags: (which) =>
        `${which}. Zmieniły się tylko reguły tagów, więc artykuły każdej wersji zostaną otagowane od nowa na podstawie tego, co już zapisano; nic nie jest pobierane. Tagi dodane ręcznie zostają.`,
      chunking: (which) =>
        `${which}. Ostatni podział na fragmenty nie powiódł się, więc zostanie uruchomiony jeszcze raz: zapisane artykuły każdej wersji zostaną od nowa podzielone na fragmenty i otagowane; nic nie jest pobierane.`,
      pathsAfterFailure: (which) =>
        `${which}. Ostatnie ponowne przetwarzanie nie powiodło się, więc tym razem zostanie wykonane w całości: każda wersja zostanie ponownie pobrana z commitu, który udostępnia, i zaimportowana z tymi ścieżkami i regułami tagów; gałęzie nie są synchronizowane.`,
      paths: (which) =>
        `${which}. Każda zostanie ponownie pobrana z commitu, który udostępnia, i zaimportowana z nowymi ścieżkami; gałęzie nie są synchronizowane.`,
      title: {
        paths: "Przetworzyć ponownie każdą wersję?",
        chunking: "Podzielić ponownie każdą wersję na fragmenty?",
        tags: "Otagować ponownie każdą wersję?",
      },
      safe: "Każda wersja udostępnia dotychczasową zawartość, dopóki nowa nie będzie kompletna, a wtedy od razu się przełącza. Wersja, której nie da się ponownie przetworzyć, zachowuje to, co miała.",
      confirm: {
        paths: "Zapisz i przetwórz ponownie",
        chunking: "Zapisz i podziel ponownie",
        tags: "Zapisz i otaguj ponownie",
      },
    },
    headline: {
      noVersion:
        "Zapisano. Biblioteka nie ma jeszcze żadnej wersji: wersje importowane od teraz będą używać tych ustawień.",
      unchanged: "Zapisano. Nic się nie zmieniło, więc nic nie jest przetwarzane ponownie.",
      tags: "Zapisano. Każda wersja jest ponownie tagowana.",
      chunking: "Zapisano. Każda wersja jest ponownie dzielona na fragmenty.",
      paths: "Zapisano. Każda wersja jest ponownie przetwarzana.",
    },
    hint: {
      unchanged: "Nic jeszcze nie zmieniono.",
      noVersion: "Nie zaimportowano jeszcze żadnej wersji, więc nic nie zostanie przetworzone.",
      confirm: "Pojawi się prośba o potwierdzenie: każda wersja zostanie przetworzona ponownie.",
    },
  },
);
