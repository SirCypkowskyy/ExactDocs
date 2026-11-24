import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";
import type { JobState } from "./model/overview";

/** Strings of the operators' overview page (blocks-map §5.2). */
export const overviewMessages = defineMessages(
  {
    title: "Overview",
    description: "This instance at a glance. Days and money in UTC.",
    loading: "Loading the overview…",
    range: "Chart range",
    days: (n: number) => plural.en(n, { one: "# day", other: "# days" }),
    tiles: {
      label: "Instance figures",
      libraries: "Libraries",
      holding: (versions: number, articles: number) =>
        `${plural.en(versions, { one: "# version", other: "# versions" })} · ${plural.en(articles, { one: "# article", other: "# articles" })}`,
      jobsToday: "Jobs today",
      failedToday: (n: number) => (n === 0 ? "none failed" : `${formatNumber(n, "en")} failed`),
      showFailed: "Show failed jobs from the last 24 hours",
      spend: "AI spend this month",
      budget: (limit: string) => `of a ${limit} monthly budget`,
      budgetUsed: "Monthly AI budget used",
      noBudget: "No monthly budget set",
      reads: "Reads this week",
      readsBreakdown: (searches: number, answers: number) =>
        `${plural.en(searches, { one: "# search", other: "# searches" })} · ${plural.en(answers, { one: "# answer", other: "# answers" })}`,
      failed: "Could not load this figure.",
    },
    charts: {
      label: "Charts",
      showTable: "Show as table",
      day: "Day",
      failed: "Could not load this chart.",
      empty: "Nothing counted in this range yet.",
      jobs: {
        title: "Jobs per day",
        figure: (n: number) => plural.en(n, { one: "# job", other: "# jobs" }),
        summary: (n: number, days: number, peak: string | null) =>
          `${plural.en(n, { one: "# job", other: "# jobs" })} queued in the last ${days} days${peak ? `, most on ${peak}` : ""}.`,
      },
      spend: {
        title: "AI spend per day",
        summary: (total: string, days: number, peak: string | null) =>
          `${total} spent in the last ${days} days${peak ? `, most on ${peak}` : ""}.`,
      },
      reads: {
        title: "Docs read per day",
        figure: (n: number) => plural.en(n, { one: "# read", other: "# reads" }),
        summary: (n: number, days: number, peak: string | null) =>
          `${plural.en(n, { one: "# read", other: "# reads" })} in the last ${days} days${peak ? `, most on ${peak}` : ""}.`,
        searches: "Searches",
        answers: "Answers",
        reads: "Reads",
      },
      usd: "Spend",
      states: {
        succeeded: "Succeeded",
        failed: "Failed",
        running: "Running",
        queued: "Queued",
        cancelled: "Cancelled",
      } satisfies Record<JobState, string>,
    },
    top: {
      title: "Most-read libraries",
      empty: "No library was read in this range.",
      several: "Searches over several libraries",
      reads: (n: number) => plural.en(n, { one: "# read", other: "# reads" }),
      share: (library: string) => `Share of reads: ${library}`,
    },
    attention: {
      title: "Needs attention",
      none: "Nothing needs attention.",
      noneBody: "Every latest sync succeeded and no AI budget is near its limit.",
      failed: "Could not check what needs attention.",
      syncFailed: "Latest sync failed",
      failedJobs: "Failed jobs",
      failedJobsOf: (library: string) => `Failed jobs of ${library}`,
      moreFailing: (n: number) =>
        plural.en(n, { one: "and # more library", other: "and # more libraries" }),
      allFailed: "Show all failed jobs",
      budget: (scope: string, window: "day" | "month", used: number) =>
        `${scope}: ${used}% of the ${window === "day" ? "daily" : "monthly"} budget used`,
      budgetReached: (scope: string, window: "day" | "month") =>
        `${scope}: the ${window === "day" ? "daily" : "monthly"} budget is reached`,
      budgetMeter: (scope: string) => `Budget used: ${scope}`,
      openAi: "Open AI settings",
      scopes: {
        instance: "Instance",
        embedding: "Embedding",
        library: (id: string) => `Library ${id}`,
        user: (id: string) => `Account ${id}`,
      },
    },
  },
  {
    title: "Przegląd",
    description: "Ta instancja w skrócie. Dni i kwoty w UTC.",
    loading: "Wczytywanie przeglądu…",
    range: "Zakres wykresów",
    days: (n) => plural.pl(n, { one: "# dzień", few: "# dni", many: "# dni" }),
    tiles: {
      label: "Liczby instancji",
      libraries: "Biblioteki",
      holding: (versions, articles) =>
        `${plural.pl(versions, { one: "# wersja", few: "# wersje", many: "# wersji" })} · ${plural.pl(articles, { one: "# artykuł", few: "# artykuły", many: "# artykułów" })}`,
      jobsToday: "Zadania dzisiaj",
      failedToday: (n) =>
        n === 0
          ? "żadne nieudane"
          : plural.pl(n, { one: "# nieudane", few: "# nieudane", many: "# nieudanych" }),
      showFailed: "Pokaż nieudane zadania z ostatnich 24 godzin",
      spend: "Wydatki na AI w tym miesiącu",
      budget: (limit) => `z miesięcznego budżetu ${limit}`,
      budgetUsed: "Wykorzystanie miesięcznego budżetu AI",
      noBudget: "Brak miesięcznego budżetu",
      reads: "Odczyty w tym tygodniu",
      readsBreakdown: (searches, answers) =>
        `${plural.pl(searches, { one: "# wyszukiwanie", few: "# wyszukiwania", many: "# wyszukiwań" })} · ${plural.pl(answers, { one: "# odpowiedź", few: "# odpowiedzi", many: "# odpowiedzi" })}`,
      failed: "Nie udało się wczytać tej liczby.",
    },
    charts: {
      label: "Wykresy",
      showTable: "Pokaż jako tabelę",
      day: "Dzień",
      failed: "Nie udało się wczytać tego wykresu.",
      empty: "W tym zakresie nic jeszcze nie policzono.",
      jobs: {
        title: "Zadania dziennie",
        figure: (n) => plural.pl(n, { one: "# zadanie", few: "# zadania", many: "# zadań" }),
        summary: (n, days, peak) =>
          `${plural.pl(n, { one: "# zadanie dodane", few: "# zadania dodane", many: "# zadań dodanych" })} w ciągu ostatnich ${days} dni${peak ? `, najwięcej ${peak}` : ""}.`,
      },
      spend: {
        title: "Wydatki na AI dziennie",
        summary: (total, days, peak) =>
          `${total} wydane w ciągu ostatnich ${days} dni${peak ? `, najwięcej ${peak}` : ""}.`,
      },
      reads: {
        title: "Odczyty dokumentacji dziennie",
        figure: (n) => plural.pl(n, { one: "# odczyt", few: "# odczyty", many: "# odczytów" }),
        summary: (n, days, peak) =>
          `${plural.pl(n, { one: "# odczyt", few: "# odczyty", many: "# odczytów" })} w ciągu ostatnich ${days} dni${peak ? `, najwięcej ${peak}` : ""}.`,
        searches: "Wyszukiwania",
        answers: "Odpowiedzi",
        reads: "Odczyty",
      },
      usd: "Wydatki",
      states: {
        succeeded: "Udane",
        failed: "Nieudane",
        running: "W toku",
        queued: "W kolejce",
        cancelled: "Anulowane",
      },
    },
    top: {
      title: "Najczęściej czytane biblioteki",
      empty: "W tym zakresie nie czytano żadnej biblioteki.",
      several: "Wyszukiwania w kilku bibliotekach",
      reads: (n) => plural.pl(n, { one: "# odczyt", few: "# odczyty", many: "# odczytów" }),
      share: (library) => `Udział w odczytach: ${library}`,
    },
    attention: {
      title: "Wymaga uwagi",
      none: "Nic nie wymaga uwagi.",
      noneBody:
        "Każda ostatnia synchronizacja się powiodła i żaden budżet AI nie jest bliski limitu.",
      failed: "Nie udało się sprawdzić, co wymaga uwagi.",
      syncFailed: "Ostatnia synchronizacja nieudana",
      failedJobs: "Nieudane zadania",
      failedJobsOf: (library) => `Nieudane zadania biblioteki ${library}`,
      moreFailing: (n) =>
        plural.pl(n, {
          one: "i # inna biblioteka",
          few: "i # inne biblioteki",
          many: "i # innych bibliotek",
        }),
      allFailed: "Pokaż wszystkie nieudane zadania",
      budget: (scope, window, used) =>
        `${scope}: wykorzystano ${used}% ${window === "day" ? "dziennego" : "miesięcznego"} budżetu`,
      budgetReached: (scope, window) =>
        `${scope}: ${window === "day" ? "dzienny" : "miesięczny"} budżet jest wyczerpany`,
      budgetMeter: (scope) => `Wykorzystanie budżetu: ${scope}`,
      openAi: "Otwórz ustawienia AI",
      scopes: {
        instance: "Instancja",
        embedding: "Embedding",
        library: (id) => `Biblioteka ${id}`,
        user: (id) => `Konto ${id}`,
      },
    },
  },
);
