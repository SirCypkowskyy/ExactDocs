import { defineMessages } from "@/shared/lib/i18n";

const code = (text: string) => <code className="font-mono text-small break-all">{text}</code>;

/** The instance banner's words (operators only). `resets` is a relative time ("in 5 hours"). */
export const messages = defineMessages(
  {
    region: "Instance notices",
    dismiss: "Dismiss",
    reindex: {
      text: () => (
        <>
          The search index needs a rebuild after the upgrade. Run {code("exactdocs reindex")} on the
          server; search keeps answering meanwhile.
        </>
      ),
      action: "Copy the command",
    },
    vectorStore: {
      text: (extension: string) => (
        <>
          Hybrid search is off: the vector store's extension, {code(extension)}, cannot be loaded.
          Searches answer with BM25 until it is installed.
        </>
      ),
      action: "Embedding status",
    },
    budget: {
      text: (window: "day" | "month", resets: string) =>
        `The instance's AI budget for ${window === "day" ? "today" : "this month"} is reached. Searches skip their paid AI steps until it resets ${resets}.`,
      action: "Usage and budgets",
    },
  },
  {
    region: "Komunikaty instancji",
    dismiss: "Zamknij komunikat",
    reindex: {
      text: () => (
        <>
          Po aktualizacji indeks wyszukiwania trzeba przebudować. Uruchom{" "}
          {code("exactdocs reindex")} na serwerze; do tego czasu wyszukiwanie działa jak dotąd.
        </>
      ),
      action: "Kopiuj polecenie",
    },
    vectorStore: {
      text: (extension) => (
        <>
          Wyszukiwanie hybrydowe jest wyłączone: nie można załadować rozszerzenia magazynu wektorów,{" "}
          {code(extension)}. Do czasu jego instalacji wyszukiwania odpowiadają przez BM25.
        </>
      ),
      action: "Stan embeddingu",
    },
    budget: {
      text: (window, resets) =>
        `${window === "day" ? "Dzienny" : "Miesięczny"} budżet AI instancji został wyczerpany. Wyszukiwania pomijają płatne kroki AI, dopóki się nie odnowi (${resets}).`,
      action: "Użycie i budżety",
    },
  },
);
