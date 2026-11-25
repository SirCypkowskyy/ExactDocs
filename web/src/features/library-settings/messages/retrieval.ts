import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";

/** The Retrieval and AI section, and the words of `model/retrieval.ts`. */
export const retrievalMessages = defineMessages(
  {
    description:
      "How searches of this library find their answers, which models they may use, and how much they may spend.",
    loading: "Loading the retrieval settings",
    effectivePipeline: "Effective pipeline",
    /** A role whose model the instance's settings could not tell. */
    configured: "configured",
    fromLibrary: " (this library)",
    fromInstance: " (instance)",
    noContentSent: "No content of this library is sent to any AI provider.",
    savedToast: "Saved the AI settings",
    useAi: "Use AI providers for this library",
    offNote:
      "Off: no chunk, query or file of this library is sent to any provider, and its searches use BM25.",
    mode: "Retrieval mode",
    modeHint: "A search can still ask for another mode. Only modes that can run now are listed.",
    instanceDefault: (mode: string) => `The instance's default (${mode})`,
    bestAvailable: "The best mode available",
    advanced: "Advanced: models, reranking and spend limits",
    customised: "Customised",
    models: "Models",
    modelsNote:
      "Use another profile's model than the instance's. The embedding model is the same for every library.",
    loadingProfiles: "Loading the profiles…",
    /** `role`: the role's label (LLM, Judge). */
    thinking: (role: string) => `${role} thinking`,
    profile: (role: string) => `${role} profile`,
    model: (role: string) => `${role} model`,
    instanceProfile: "The instance's",
    instanceProfileJudge: "The instance's (else the LLM)",
    rerankTopN: "Candidates to rerank",
    rerankTopNHint: (most: number) => `1 to ${most}. Empty: the instance's number.`,
    rerankWith: "Rerank with",
    rerankWithHint:
      "The LLM judge rates every candidate in one call, counted against the spend limits. It reranks only where it is chosen and its model (else the LLM) is configured.",
    instanceChoice: (label: string) => `The instance's choice (${label})`,
    repoGuidance: "Repository guidance (AGENTS.md / CLAUDE.md)",
    /** `hint`: what the chosen guidance does. */
    guidanceHint: (hint: string) => `${hint} Turning it on re-imports this library's versions.`,
    spendLimits: "Spend limits",
    spendNote:
      "Per UTC day and month. Once one is used up, searches skip the paid step and say why. Empty: only the instance's limits apply.",
    dailyUsd: "US dollars per day",
    monthlyUsd: "US dollars per month",
    dailyTokens: "Tokens per day",
    monthlyTokens: "Tokens per month",
    save: "Save AI settings",
    rerankWithLabel: {
      cross_encoder: "Cross-encoder (cheaper)",
      judge: "LLM judge",
    },
    guidance: {
      off: { label: "Off", hint: "Imports keep no instruction file." },
      notes: {
        label: "Untrusted notes",
        hint: "Each version keeps its AGENTS.md / CLAUDE.md files; the agent gets a folder's file as a note when it opens that folder, never as instructions.",
      },
      trusted: {
        label: "Trusted instructions",
        hint: "As notes, and the root file also becomes part of the agent's instructions. Only for a repository you trust as much as your own instructions.",
      },
    },
    modes: {
      bm25: "BM25",
      vector: "Vector",
      hybrid: "Hybrid",
      hybrid_hyde: "Hybrid with HyDE",
      agentic: "Agentic",
    },
    cantRunNow: (mode: string) => `${mode} (can't run now)`,
    notAvailable: " (not available)",
    steps: {
      keyword: "Keyword search (BM25)",
      vector: "Vector search with the embedding model",
      merged: "Results merged",
      hyde: "The LLM writes a hypothetical answer (HyDE)",
      agentBrowses:
        "An LLM agent browses this version in a sandbox: outlines, articles, chunks and keyword search",
      agentChecked: "Its picks are checked against this version, each with why it was picked",
      guidanceTrusted:
        "The repository's root AGENTS.md / CLAUDE.md is part of its instructions; a folder's is a note when it opens it",
      guidanceNotes:
        "A folder's AGENTS.md / CLAUDE.md reaches it as an untrusted note when it opens the folder",
      reranker: (top: number) => `The reranker reorders the best ${top}`,
      judge: (top: number) => `The LLM judge rates the best ${top} in one call and reorders them`,
    },
    fallback: {
      agent_limit_reached: "The agent ran past its limits, so a cheaper mode answered.",
      agent_failed: "The agent could not finish, so a cheaper mode answered.",
      agent_loop_detected: "The agent kept repeating the same call, so a cheaper mode answered.",
      mode_unavailable:
        "The mode set for it can't run now: a model role it needs is not configured.",
      vector_store_unavailable: "The vector store can't be loaded, so the vector modes are off.",
      /** `reason`: the server's code, for a reason without words of its own. */
      other: (reason: string) => `It fell back (${reason}).`,
    },
    source: {
      aiOff: "AI is off for this library.",
      library: "Set for this library.",
      instance: "The instance's default.",
      best: "The best mode the instance has configured.",
    },
    instanceLevel: "The instance's level",
    instanceLevelOf: (level: string) => `The instance's level (${level})`,
    /** A budget's amount, with its unit. */
    amount: {
      USD: (n: number) => `${formatNumber(n, "en")} USD`,
      tokens: (n: number) => `${formatNumber(n, "en")} tokens`,
    },
    /** `most`: the instance's limit, with its unit. */
    ceilingAbove: (most: string) =>
      `Above the instance's limit of ${most}, which applies instead. It can be kept or lowered, not raised.`,
    ceilingAtMost: (most: string) => `At most ${most}, the instance's limit.`,
    noCeiling: "The instance sets no limit here.",
    nameModel: "Name the model to use.",
    wholeTopN: (most: number) => `Enter a whole number from 1 to ${most}, or leave it empty.`,
    wholeTokens: "Enter a whole number of tokens above 0, or leave it empty.",
    amountAbove: "Enter an amount above 0, or leave it empty.",
    instanceAllows: (most: string) => `The instance allows a library at most ${most}.`,
  },
  {
    description:
      "Jak wyszukiwania w tej bibliotece znajdują odpowiedzi, z jakich modeli mogą korzystać i ile mogą wydać.",
    loading: "Wczytywanie ustawień wyszukiwania",
    effectivePipeline: "Potok w użyciu",
    configured: "skonfigurowany",
    fromLibrary: " (ta biblioteka)",
    fromInstance: " (instancja)",
    noContentSent: "Żadna treść tej biblioteki nie jest wysyłana do żadnego dostawcy AI.",
    savedToast: "Zapisano ustawienia AI",
    useAi: "Używaj dostawców AI w tej bibliotece",
    offNote:
      "Wyłączone: żaden fragment, zapytanie ani plik tej biblioteki nie trafia do żadnego dostawcy, a wyszukiwania używają BM25.",
    mode: "Tryb wyszukiwania",
    modeHint:
      "Wyszukiwanie może nadal poprosić o inny tryb. Na liście są tylko tryby, które mogą teraz działać.",
    instanceDefault: (mode) => `Domyślny dla instancji (${mode})`,
    bestAvailable: "Najlepszy dostępny tryb",
    advanced: "Zaawansowane: modele, reranking i limity wydatków",
    customised: "Dostosowane",
    models: "Modele",
    modelsNote:
      "Użyj modelu z innego profilu niż ten, którego używa instancja. Model embeddingów jest wspólny dla wszystkich bibliotek.",
    loadingProfiles: "Wczytywanie profili…",
    thinking: (role) => `Poziom myślenia (${role})`,
    profile: (role) => `Profil (${role})`,
    model: (role) => `Model (${role})`,
    instanceProfile: "Z instancji",
    instanceProfileJudge: "Z instancji (lub LLM)",
    rerankTopN: "Kandydaci do rerankingu",
    rerankTopNHint: (most) => `Od 1 do ${formatNumber(most, "pl")}. Puste: liczba z instancji.`,
    rerankWith: "Reranking za pomocą",
    rerankWithHint:
      "Sędzia LLM ocenia wszystkich kandydatów w jednym wywołaniu, które wlicza się do limitów wydatków. Zmienia kolejność tylko tam, gdzie go wybrano i gdzie skonfigurowano jego model (lub model LLM).",
    instanceChoice: (label) => `Wybór instancji (${label})`,
    repoGuidance: "Wskazówki z repozytorium (AGENTS.md / CLAUDE.md)",
    guidanceHint: (hint) => `${hint} Włączenie tej opcji importuje ponownie wersje tej biblioteki.`,
    spendLimits: "Limity wydatków",
    spendNote:
      "Na dobę i miesiąc według UTC. Gdy któryś limit się wyczerpie, wyszukiwania pomijają płatny krok i podają powód. Puste: obowiązują tylko limity instancji.",
    dailyUsd: "Dolary amerykańskie dziennie",
    monthlyUsd: "Dolary amerykańskie miesięcznie",
    dailyTokens: "Tokeny dziennie",
    monthlyTokens: "Tokeny miesięcznie",
    save: "Zapisz ustawienia AI",
    rerankWithLabel: {
      cross_encoder: "Cross-encoder (tańszy)",
      judge: "Sędzia LLM",
    },
    guidance: {
      off: { label: "Wyłączone", hint: "Importy nie zachowują żadnych plików z instrukcjami." },
      notes: {
        label: "Niezaufane notatki",
        hint: "Każda wersja zachowuje swoje pliki AGENTS.md / CLAUDE.md; agent dostaje plik folderu jako notatkę, gdy otwiera ten folder, nigdy jako instrukcje.",
      },
      trusted: {
        label: "Zaufane instrukcje",
        hint: "Jak notatki, a dodatkowo plik z katalogu głównego staje się częścią instrukcji agenta. Tylko dla repozytorium, któremu ufasz tak jak własnym instrukcjom.",
      },
    },
    modes: {
      bm25: "BM25",
      vector: "Wektorowe",
      hybrid: "Hybrydowe",
      hybrid_hyde: "Hybrydowe z HyDE",
      agentic: "Agentowe",
    },
    cantRunNow: (mode) => `${mode} (nie może teraz działać)`,
    notAvailable: " (niedostępny)",
    steps: {
      keyword: "Wyszukiwanie po słowach kluczowych (BM25)",
      vector: "Wyszukiwanie wektorowe modelem embeddingów",
      merged: "Scalenie wyników",
      hyde: "LLM pisze hipotetyczną odpowiedź (HyDE)",
      agentBrowses:
        "Agent LLM przegląda tę wersję w piaskownicy: spisy nagłówków, artykuły, fragmenty i wyszukiwanie po słowach kluczowych",
      agentChecked: "Jego wybory są sprawdzane względem tej wersji, każdy z uzasadnieniem wyboru",
      guidanceTrusted:
        "Główny plik AGENTS.md / CLAUDE.md repozytorium jest częścią jego instrukcji; plik folderu jest notatką, gdy agent otwiera ten folder",
      guidanceNotes:
        "Plik AGENTS.md / CLAUDE.md folderu trafia do agenta jako niezaufana notatka, gdy ten otwiera folder",
      reranker: (top) => `Reranker zmienia kolejność ${formatNumber(top, "pl")} najlepszych`,
      judge: (top) =>
        `Sędzia LLM ocenia ${formatNumber(top, "pl")} najlepszych w jednym wywołaniu i zmienia ich kolejność`,
    },
    fallback: {
      agent_limit_reached: "Agent przekroczył swoje limity, więc odpowiedział tańszy tryb.",
      agent_failed: "Agent nie zdołał dokończyć pracy, więc odpowiedział tańszy tryb.",
      agent_loop_detected: "Agent powtarzał to samo wywołanie, więc odpowiedział tańszy tryb.",
      mode_unavailable:
        "Ustawiony tryb nie może teraz działać: potrzebna mu rola modelu nie jest skonfigurowana.",
      vector_store_unavailable:
        "Nie można wczytać magazynu wektorów, więc tryby wektorowe są wyłączone.",
      other: (reason) => `Użyto trybu zapasowego (${reason}).`,
    },
    source: {
      aiOff: "AI jest wyłączone dla tej biblioteki.",
      library: "Ustawiony dla tej biblioteki.",
      instance: "Domyślny dla instancji.",
      best: "Najlepszy tryb skonfigurowany w instancji.",
    },
    instanceLevel: "Poziom instancji",
    instanceLevelOf: (level) => `Poziom instancji (${level})`,
    amount: {
      USD: (n) => `${formatNumber(n, "pl")} USD`,
      tokens: (n) =>
        plural.pl(n, {
          one: "# token",
          few: "# tokeny",
          many: "# tokenów",
          other: "# tokena",
        }),
    },
    ceilingAbove: (most) =>
      `Powyżej limitu instancji (${most}), który obowiązuje zamiast niego. Można go zachować lub obniżyć, ale nie podnieść.`,
    ceilingAtMost: (most) => `Najwyżej ${most} – to limit instancji.`,
    noCeiling: "Instancja nie ustala tu limitu.",
    nameModel: "Podaj nazwę modelu.",
    wholeTopN: (most) =>
      `Wpisz liczbę całkowitą od 1 do ${formatNumber(most, "pl")} albo zostaw puste pole.`,
    wholeTokens: "Wpisz całkowitą liczbę tokenów większą od 0 albo zostaw puste pole.",
    amountAbove: "Wpisz kwotę większą od 0 albo zostaw puste pole.",
    instanceAllows: (most) => `Instancja pozwala bibliotece na najwyżej ${most}.`,
  },
);
