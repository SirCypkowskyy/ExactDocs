import { aiLabels } from "@/shared/lib/ai-queries";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";

/*
 * The instance AI page's strings: providers and roles, embedding progress, usage and budgets.
 * Profile names, models, URLs and the server's reasons stay as they came.
 */

const money = {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
} as const;

export const messages = defineMessages(
  {
    usd: (n: number) => formatNumber(n, "en", money),
    count: (n: number) => formatNumber(n, "en"),
    /** Each model role and thinking level, in the words every screen uses (shared/lib). */
    roles: aiLabels.en.roles,
    thinkingLevels: aiLabels.en.thinking,
    page: {
      title: "AI",
      description:
        "The providers and models this instance uses, how far embedding has got, and what AI calls spent. Keys are never shown.",
    },
    providers: {
      title: "Providers and roles",
      description:
        "Each role is a model of a provider profile. Check a profile to make one small call per role that uses it.",
      loadingRoles: "Loading the roles",
      loading: "Loading the providers",
      noneTitle: "No provider is configured",
      none: "Searches use BM25 and nothing leaves the instance. Add a provider profile to the instance configuration to turn on embeddings or an LLM.",
      llms: " (the LLM's)",
      noProfile: " (its profile does not exist)",
      notSet: "Not set",
      notSetHint:
        "A role that is not set has no model yet: choose it in the instance configuration.",
      key: {
        sealed: "Key stored, sealed",
        file: "Key read from a file",
        environment: "Key from the environment",
        none: "No key",
      },
      fromConfiguration: "Configuration (read-only)",
      fromApi: "Added over the API",
      usedFor: (roles: string) => `Used for: ${roles}`,
      unused: "No instance role uses it.",
      check: "Check",
      checkLabel: (name: string) => `Check ${name}`,
      checkStatus: (name: string) => `${name} check`,
      allPassed: (name: string) => `${name}: every check passed`,
      someFailed: (name: string, failed: number, total: number) =>
        `${name}: ${failed} of ${total} checks failed`,
      model: "Model",
      ok: "OK. ",
      failed: "Failed. ",
      callFailed: "The call failed.",
      answered: (ms: number, servedModel: string | null, dimensions: number | null) =>
        `Answered in ${ms} ms${servedModel ? ` by ${servedModel}` : ""}${dimensions ? `, ${dimensions} dimensions` : ""}`,
    },
    thinking: {
      label: { llm: "LLM thinking", judge: "Judge thinking" },
      set: (role: "llm" | "judge", level: string) =>
        `${role === "llm" ? "LLM" : "Judge"} thinking set to ${level.toLowerCase()}`,
      reset: (role: "llm" | "judge") =>
        `${role === "llm" ? "LLM" : "Judge"} thinking back to the default`,
      configured: (role: "llm" | "judge") =>
        `Set in the configuration (EXACTDOCS_AI__${role.toUpperCase()}__THINKING).`,
      hint: aiLabels.en.thinkingHint,
      unsupported: (reason: string) =>
        `Its model takes no thinking level, so its calls leave it out: ${reason}.`,
      inherited: (level: string) => `The LLM's level (${level})`,
      providerDefault: "The provider's default",
    },
    embedding: {
      title: "Embedding",
      description:
        "Every version of a library with AI on is embedded in the background. While a new model embeds, the old space keeps answering.",
      loading: "Loading the embedding progress",
      model: "Model:",
      noModel: "none configured",
      emptyTitle: "Nothing has been embedded yet",
      empty: "Embedding starts when a library has AI on and a model is set for the embedding role.",
      space: (id: number, model: string) => `Space ${id}: ${model}`,
      searched: "Searched",
      building: "Building",
      current: "Configured model",
      retiring: "Retired once the new one is done",
      dimensions: (n: number) => `${n} dimensions`,
      created: (when: string) => `created ${when}`,
      progressLabel: (space: string) => `${space} progress`,
      progress: (
        done: number,
        chunksEmbedded: number,
        chunks: number,
        versionsEmbedded: number,
        versions: number,
      ) =>
        `${done}%: ${formatNumber(chunksEmbedded, "en")} of ${formatNumber(chunks, "en")} chunks, ${formatNumber(versionsEmbedded, "en")} of ${formatNumber(versions, "en")} versions`,
    },
    usage: {
      title: "Usage and budgets",
      description:
        "What AI calls spent today and this month (UTC), and what is left of each budget. A used-up budget skips the paid step; searches still answer.",
      loading: "Loading the usage",
      searchesPerMinute: "LLM searches per minute per caller: ",
      notLimited: "not limited",
      table: "Usage table",
      scope: "Scope",
      today: "Today",
      thisMonth: "This month",
      budgets: "Budgets",
      scopes: {
        instance: "The instance",
        embedding: "Embedding runs",
        library: (id: string) => `Library ${id}`,
        account: (id: string) => `Account ${id}`,
      },
      /** "3,000 tokens (+1,200 local, not budgeted) · 3 calls, 1 unpriced". */
      spent: (tokens: number, local: number, calls: number, unpriced: number) =>
        `${plural.en(tokens, { one: "# token", other: "# tokens" })}${local ? ` (+${formatNumber(local, "en")} local, not budgeted)` : ""} · ${plural.en(calls, { one: "# call", other: "# calls" })}${unpriced ? `, ${formatNumber(unpriced, "en")} unpriced` : ""}`,
      usdLeft: (left: string, limit: string) => `${left} of ${limit} left`,
      tokensLeft: (left: number, limit: number) =>
        `${formatNumber(left, "en")} of ${formatNumber(limit, "en")} tokens left`,
      budget: (window: "day" | "month", parts: string) =>
        `${window === "day" ? "Today" : "This month"}: ${parts}`,
      reachedUntil: (when: string) => ` · reached until ${when}`,
      used: (window: "day" | "month") =>
        `${window === "day" ? "Today's" : "This month's"} budget used`,
      tokens: (n: number) => plural.en(n, { one: "# token", other: "# tokens" }),
      ownBudget: (own: string) =>
        `The instance limit is lower than the library's own budget (${own}), so it applies.`,
    },
    /** A failed read or check, in words. */
    errors: {
      offline: "Can't reach the server. Check your connection.",
      sessionEnded: "Your session ended. Sign in again.",
      adminsOnly: "Only admins can see the instance's AI settings.",
      other: (status: number) =>
        `Something went wrong on the server (${status}). Try again in a moment.`,
    },
  },
  {
    usd: (n) => formatNumber(n, "pl", money),
    count: (n) => formatNumber(n, "pl"),
    roles: aiLabels.pl.roles,
    thinkingLevels: aiLabels.pl.thinking,
    page: {
      title: "AI",
      description:
        "Dostawcy i modele używane przez tę instancję, postęp embeddingu i koszty wywołań AI. Klucze nigdy nie są wyświetlane.",
    },
    providers: {
      title: "Dostawcy i role",
      description:
        "Każda rola to model z profilu dostawcy. Sprawdzenie profilu wykonuje jedno małe wywołanie dla każdej roli, która go używa.",
      loadingRoles: "Wczytywanie ról",
      loading: "Wczytywanie dostawców",
      noneTitle: "Nie skonfigurowano żadnego dostawcy",
      none: "Wyszukiwanie używa BM25 i nic nie opuszcza instancji. Dodaj profil dostawcy do konfiguracji instancji, aby włączyć embeddingi lub LLM.",
      llms: " (z roli LLM)",
      noProfile: " (jego profil nie istnieje)",
      notSet: "Nie ustawiono",
      notSetHint:
        "Rola, która nie jest ustawiona, nie ma jeszcze modelu: wybierz go w konfiguracji instancji.",
      key: {
        sealed: "Klucz zapisany, zaszyfrowany",
        file: "Klucz odczytywany z pliku",
        environment: "Klucz ze zmiennej środowiskowej",
        none: "Brak klucza",
      },
      fromConfiguration: "Konfiguracja (tylko do odczytu)",
      fromApi: "Dodany przez API",
      usedFor: (roles) => `Używany w rolach: ${roles}`,
      unused: "Nie używa go żadna rola instancji.",
      check: "Sprawdź",
      checkLabel: (name) => `Sprawdź ${name}`,
      checkStatus: (name) => `Sprawdzenie ${name}`,
      allPassed: (name) => `${name}: wszystkie sprawdzenia przebiegły pomyślnie`,
      someFailed: (name, failed, total) =>
        `${name} – nieudane sprawdzenia: ${formatNumber(failed, "pl")} z ${formatNumber(total, "pl")}`,
      model: "Model",
      ok: "OK. ",
      failed: "Błąd. ",
      callFailed: "Wywołanie nie powiodło się.",
      answered: (ms, servedModel, dimensions) =>
        `Odpowiedź w ${formatNumber(ms, "pl")} ms${servedModel ? `, model ${servedModel}` : ""}${dimensions ? `, ${plural.pl(dimensions, { one: "# wymiar", few: "# wymiary", many: "# wymiarów" })}` : ""}`,
    },
    thinking: {
      label: { llm: "Myślenie LLM", judge: "Myślenie sędziego" },
      set: (role, level) =>
        `${role === "llm" ? "Myślenie LLM" : "Myślenie sędziego"} ustawione na poziom „${level.toLowerCase()}”`,
      reset: (role) =>
        `${role === "llm" ? "Myślenie LLM" : "Myślenie sędziego"} przywrócone do domyślnego`,
      configured: (role) =>
        `Ustawiony w konfiguracji (EXACTDOCS_AI__${role.toUpperCase()}__THINKING).`,
      hint: aiLabels.pl.thinkingHint,
      unsupported: (reason) =>
        `Model tej roli nie przyjmuje poziomu myślenia, więc wywołania go pomijają: ${reason}.`,
      inherited: (level) => `Poziom roli LLM (${level})`,
      providerDefault: "Domyślny poziom dostawcy",
    },
    embedding: {
      title: "Embedding",
      description:
        "Każda wersja biblioteki z włączonym AI jest w tle przetwarzana na embeddingi. Dopóki trwa embedding nowym modelem, odpowiada stara przestrzeń.",
      loading: "Wczytywanie postępu embeddingu",
      model: "Model:",
      noModel: "nie skonfigurowano",
      emptyTitle: "Jeszcze nic nie przetworzono na embeddingi",
      empty:
        "Embedding rusza, gdy biblioteka ma włączone AI, a dla roli embeddingu ustawiono model.",
      space: (id, model) => `Przestrzeń ${id}: ${model}`,
      searched: "Przeszukiwana",
      building: "W budowie",
      current: "Skonfigurowany model",
      retiring: "Zostanie wycofana po ukończeniu nowej",
      dimensions: (n) => plural.pl(n, { one: "# wymiar", few: "# wymiary", many: "# wymiarów" }),
      created: (when) => `utworzona ${when}`,
      progressLabel: (space) => `Postęp: ${space}`,
      progress: (done, chunksEmbedded, chunks, versionsEmbedded, versions) =>
        `${done}%: ${formatNumber(chunksEmbedded, "pl")} z ${plural.pl(chunks, { one: "# fragmentu", few: "# fragmentów", many: "# fragmentów" })}, ${formatNumber(versionsEmbedded, "pl")} z ${formatNumber(versions, "pl")} wersji`,
    },
    usage: {
      title: "Zużycie i budżety",
      description:
        "Ile wydały wywołania AI dziś i w tym miesiącu (UTC) oraz ile zostało z każdego budżetu. Po wyczerpaniu budżetu płatny krok jest pomijany; wyszukiwanie nadal odpowiada.",
      loading: "Wczytywanie zużycia",
      searchesPerMinute: "Wyszukiwania LLM na minutę dla jednego wywołującego: ",
      notLimited: "bez limitu",
      table: "Tabela zużycia",
      scope: "Zakres",
      today: "Dziś",
      thisMonth: "Ten miesiąc",
      budgets: "Budżety",
      scopes: {
        instance: "Instancja",
        embedding: "Przebiegi embeddingu",
        library: (id) => `Biblioteka ${id}`,
        account: (id) => `Konto ${id}`,
      },
      spent: (tokens, local, calls, unpriced) =>
        `${plural.pl(tokens, { one: "# token", few: "# tokeny", many: "# tokenów" })}${local ? ` (+${formatNumber(local, "pl")} lokalnie, poza budżetem)` : ""} · ${plural.pl(calls, { one: "# wywołanie", few: "# wywołania", many: "# wywołań" })}${unpriced ? `, bez wyceny: ${formatNumber(unpriced, "pl")}` : ""}`,
      usdLeft: (left, limit) => `zostało ${left} z ${limit}`,
      tokensLeft: (left, limit) =>
        `zostało ${formatNumber(left, "pl")} z ${plural.pl(limit, { one: "# tokena", few: "# tokenów", many: "# tokenów" })}`,
      budget: (window, parts) => `${window === "day" ? "Dziś" : "W tym miesiącu"}: ${parts}`,
      reachedUntil: (when) => ` · wyczerpany do ${when}`,
      used: (window) =>
        window === "day"
          ? "Wykorzystanie dzisiejszego budżetu"
          : "Wykorzystanie budżetu na ten miesiąc",
      tokens: (n) => plural.pl(n, { one: "# token", few: "# tokeny", many: "# tokenów" }),
      ownBudget: (own) =>
        `Limit instancji jest niższy niż własny budżet biblioteki (${own}), więc to on obowiązuje.`,
    },
    errors: {
      offline: "Nie można połączyć się z serwerem. Sprawdź połączenie.",
      sessionEnded: "Twoja sesja wygasła. Zaloguj się ponownie.",
      adminsOnly: "Tylko administratorzy widzą ustawienia AI instancji.",
      other: (status) =>
        `Coś poszło nie tak po stronie serwera (${status}). Spróbuj ponownie za chwilę.`,
    },
  },
);
