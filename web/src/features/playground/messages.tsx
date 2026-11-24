import type { ReactNode } from "react";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";
import type { AnswerResult, FallbackReason, PlaygroundMode } from "./model/playground";

/*
 * The playground's strings: the query form, each mode's results and the agent's answer. Hits,
 * snippets, the answer and the reasons the server gives stay as they came.
 */

type NoAnswerReason = NonNullable<AnswerResult["fallback_reason"]>;
type Usage = AnswerResult["usage"];

const usdEn = (n: number) =>
  formatNumber(n, "en", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  });
const usdPl = (n: number) =>
  formatNumber(n, "pl", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  });
const scoreFormat = { minimumFractionDigits: 4, maximumFractionDigits: 4 } as const;

export const messages = defineMessages(
  {
    modes: {
      bm25: "BM25 (keywords)",
      vector: "Vector (embeddings)",
      hybrid: "Hybrid (BM25 + vectors)",
    } satisfies Record<PlaygroundMode, string>,
    page: {
      title: "Search playground",
      description:
        "Run one query across the libraries you choose and compare how BM25, vector and hybrid search rank it.",
      form: "Playground query",
      query: "Query",
      queryPlaceholder: "how do I retry failed calls",
      libraries: "Libraries",
      allLibraries: "All libraries",
      mode: "Mode",
      compareWith: "Compare with",
      compare: "Compare two modes side by side",
      agentNote:
        "An LLM searches and reads the chosen libraries and writes an answer. It counts to the LLM budgets and rate limit like an agentic search.",
      ask: "Ask the agent",
      agentOption: "Agent answer (an LLM reads and answers)",
      agentOptionUnavailable: "Agent answer (unavailable)",
      agentUnavailable: (reason: string) => `Agent answer is unavailable: ${reason}`,
      agentCantRun: "it can't run now",
    },
    results: {
      list: (mode: string) => `${mode} results`,
      searching: "Searching…",
      unavailable: (message: string) => `Unavailable: ${message}`,
      answeredBy: (mode: ReactNode, results: number, libraries: number) => (
        <>
          Answered by {mode}
          {" · "}
          {plural.en(results, { one: "# result", other: "# results" })} from{" "}
          {plural.en(libraries, { one: "# library", other: "# libraries" })}
        </>
      ),
      withoutVectors: (libraries: string) =>
        `Not in the vector ranking (AI off or not embedded yet): ${libraries}`,
      none: "No results",
      noneHint: "Try other words, or choose more libraries.",
      scoreTitle: "Score in the mode that answered",
      score: (score: number) => `score ${formatNumber(score, "en", scoreFormat)}`,
      version: "version ",
      bm25Rank: (rank: number) => `BM25 #${rank}`,
      vectorRank: (rank: number) => `vector #${rank}`,
      /** Why BM25 answered instead of the mode asked for. */
      fallback: (why: string) => `BM25 answered instead: ${why}`,
      fallbacks: {
        embedding_in_progress: "No chosen library is embedded with the current model yet.",
        embedding_unavailable: "The embedding model failed on the query.",
        vector_store_unavailable: "The vector store can't be loaded here.",
        llm_budget_reached: "A budget the query embedding counts to is used up.",
        mode_unavailable: "The mode can't run now.",
      } satisfies Partial<Record<FallbackReason, string>>,
    },
    agent: {
      heading: "Agent answer",
      starting: "The agent is starting…",
      progress: (calls: number, max: number) => `The agent has made ${calls} of ${max} tool calls…`,
      failed: "The agent failed.",
      streamEnded: "The answer stream ended without an answer.",
      noAnswer: (why: string) => `No answer: ${why}`,
      notRead: (libraries: string) => `Not read (AI is off for them): ${libraries}`,
      toolCalls: (calls: number, max: number) => `${calls} of ${max} tool calls`,
      spend: (usage: Usage) =>
        `${plural.en(usage.requests, { one: "# model request", other: "# model requests" })}, ${formatNumber(usage.input_tokens, "en")} in / ${formatNumber(usage.output_tokens, "en")} out tokens${usage.cost_usd === null ? "" : `, ${usdEn(usage.cost_usd)}`}`,
      readBeforeStop: "Read before it stopped",
      sources: "Sources",
      /** Why the agent did not answer. */
      noAnswers: {
        agent_limit_reached: "The agent used up its tool calls or time before it could answer.",
        agent_loop_detected: "The agent repeated itself and was stopped.",
        agent_failed: "The agent failed.",
        llm_budget_reached: "A budget this run counts to is used up.",
        llm_rate_limited: "Too many LLM searches this minute.",
        mode_unavailable: "No chosen library may be sent to the LLM (AI is off for it).",
      } satisfies Partial<Record<NoAnswerReason, string>>,
    },
  },
  {
    modes: {
      bm25: "BM25 (słowa kluczowe)",
      vector: "Wektorowe (embeddingi)",
      hybrid: "Hybrydowe (BM25 + wektory)",
    },
    page: {
      title: "Piaskownica wyszukiwania",
      description:
        "Uruchom jedno zapytanie w wybranych bibliotekach i porównaj, jak szeregują je wyszukiwanie BM25, wektorowe i hybrydowe.",
      form: "Zapytanie w piaskownicy",
      query: "Zapytanie",
      queryPlaceholder: "jak ponawiać nieudane wywołania",
      libraries: "Biblioteki",
      allLibraries: "Wszystkie biblioteki",
      mode: "Tryb",
      compareWith: "Porównaj z",
      compare: "Porównaj dwa tryby obok siebie",
      agentNote:
        "LLM przeszukuje i czyta wybrane biblioteki, a potem pisze odpowiedź. Wlicza się do budżetów i limitu zapytań LLM tak jak wyszukiwanie agentowe.",
      ask: "Zapytaj agenta",
      agentOption: "Odpowiedź agenta (LLM czyta i odpowiada)",
      agentOptionUnavailable: "Odpowiedź agenta (niedostępna)",
      agentUnavailable: (reason) => `Odpowiedź agenta jest niedostępna: ${reason}`,
      agentCantRun: "nie może teraz działać",
    },
    results: {
      list: (mode) => `Wyniki: ${mode}`,
      searching: "Wyszukiwanie…",
      unavailable: (message) => `Niedostępne: ${message}`,
      answeredBy: (mode, results, libraries) => (
        <>
          Odpowiedział tryb {mode}
          {" · "}
          {plural.pl(results, { one: "# wynik", few: "# wyniki", many: "# wyników" })} z{" "}
          {plural.pl(libraries, { one: "# biblioteki", few: "# bibliotek", many: "# bibliotek" })}
        </>
      ),
      withoutVectors: (libraries) =>
        `Poza rankingiem wektorowym (AI wyłączone lub jeszcze bez embeddingów): ${libraries}`,
      none: "Brak wyników",
      noneHint: "Spróbuj innych słów lub wybierz więcej bibliotek.",
      scoreTitle: "Punktacja w trybie, który odpowiedział",
      score: (score) => `punktacja ${formatNumber(score, "pl", scoreFormat)}`,
      version: "wersja ",
      bm25Rank: (rank) => `BM25 #${rank}`,
      vectorRank: (rank) => `wektorowe #${rank}`,
      fallback: (why) => `Zamiast tego odpowiedział BM25: ${why}`,
      fallbacks: {
        embedding_in_progress:
          "Żadna z wybranych bibliotek nie ma jeszcze embeddingów z bieżącego modelu.",
        embedding_unavailable: "Model embeddingów nie przetworzył zapytania.",
        vector_store_unavailable: "Nie można tu wczytać bazy wektorowej.",
        llm_budget_reached: "Budżet, do którego wlicza się embedding zapytania, został wyczerpany.",
        mode_unavailable: "Ten tryb nie może teraz działać.",
      },
    },
    agent: {
      heading: "Odpowiedź agenta",
      starting: "Agent się uruchamia…",
      progress: (calls, max) =>
        `Agent wykonał ${formatNumber(calls, "pl")} z ${plural.pl(max, { one: "# wywołania", few: "# wywołań", many: "# wywołań" })} narzędzi…`,
      failed: "Działanie agenta nie powiodło się.",
      streamEnded: "Strumień odpowiedzi zakończył się bez odpowiedzi.",
      noAnswer: (why) => `Brak odpowiedzi: ${why}`,
      notRead: (libraries) => `Nieprzeczytane (AI jest dla nich wyłączone): ${libraries}`,
      toolCalls: (calls, max) =>
        `${formatNumber(calls, "pl")} z ${plural.pl(max, { one: "# wywołania", few: "# wywołań", many: "# wywołań" })} narzędzi`,
      spend: (usage) =>
        `${plural.pl(usage.requests, { one: "# żądanie do modelu", few: "# żądania do modelu", many: "# żądań do modelu" })}, tokeny: ${formatNumber(usage.input_tokens, "pl")} wejściowe / ${formatNumber(usage.output_tokens, "pl")} wyjściowe${usage.cost_usd === null ? "" : `, ${usdPl(usage.cost_usd)}`}`,
      readBeforeStop: "Przeczytane przed zatrzymaniem",
      sources: "Źródła",
      noAnswers: {
        agent_limit_reached:
          "Agent wyczerpał limit wywołań narzędzi lub czasu, zanim zdążył odpowiedzieć.",
        agent_loop_detected: "Agent zapętlił się i został zatrzymany.",
        agent_failed: "Działanie agenta nie powiodło się.",
        llm_budget_reached: "Budżet, do którego wlicza się ten przebieg, został wyczerpany.",
        llm_rate_limited: "Za dużo wyszukiwań LLM w tej minucie.",
        mode_unavailable:
          "Żadnej z wybranych bibliotek nie można wysłać do LLM (AI jest dla nich wyłączone).",
      },
    },
  },
);

export type PlaygroundMessages = (typeof messages)["en"];
