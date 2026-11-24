import { defineMessages, plural } from "@/shared/lib/i18n";
import type { Metric, Period, Subject } from "./model/leaderboard";

/** Strings of the leaderboard (blocks-map §5.3). */
export const leaderboardMessages = defineMessages(
  {
    title: "Leaderboard",
    description: "What was read, searched and asked most. Periods are UTC; the current one so far.",
    loading: "Loading the leaderboard…",
    controls: "Board",
    subject: "Ranked",
    metric: "By",
    period: "Over",
    subjects: { libraries: "Libraries", people: "People" } satisfies Record<Subject, string>,
    metrics: {
      reads: "Docs read",
      searches: "Searches",
      answers: "Agent answers",
    } satisfies Record<Metric, string>,
    periods: {
      day: "Day",
      week: "Week",
      month: "Month",
      year: "Year",
    } satisfies Record<Period, string>,
    /** A value with its unit: "128 reads". */
    value: {
      reads: (n: number) => plural.en(n, { one: "# read", other: "# reads" }),
      searches: (n: number) => plural.en(n, { one: "# search", other: "# searches" }),
      answers: (n: number) => plural.en(n, { one: "# answer", other: "# answers" }),
    } satisfies Record<Metric, (n: number) => string>,
    range: (start: string, end: string) => (start === end ? start : `${start} – ${end}`),
    top: "Top ten",
    /** One column, as a screen reader reads it: "3. alice, 128 reads". */
    item: (rank: number, name: string, value: string) => `${rank}. ${name}, ${value}`,
    you: "You",
    youSuffix: " (you)",
    movement: {
      up: (by: number, from: number) => `up ${by} from #${from}`,
      down: (by: number, from: number) => `down ${by} from #${from}`,
      same: (from: number) => `same as before, #${from}`,
      new: "new this period",
      newShort: "New",
    },
    columns: {
      rank: "Rank",
      library: "Library",
      person: "Person",
      value: "Count",
      share: "Share",
      change: "Change",
    },
    shareOf: (name: string) => `Share of the period: ${name}`,
    rest: "Ranks 11 and up",
    find: "Find on the board",
    findLibrary: "Library ID",
    findPerson: "Username",
    noMatch: "Nobody on the board matches.",
    yourRank: (rank: number, value: string) => `You · #${rank} · ${value}`,
    empty: {
      reads: {
        day: "Nothing read today yet.",
        week: "Nothing read this week yet.",
        month: "Nothing read this month yet.",
        year: "Nothing read this year yet.",
      },
      searches: {
        day: "No searches today yet.",
        week: "No searches this week yet.",
        month: "No searches this month yet.",
        year: "No searches this year yet.",
      },
      answers: {
        day: "No agent answers today yet.",
        week: "No agent answers this week yet.",
        month: "No agent answers this month yet.",
        year: "No agent answers this year yet.",
      },
    } satisfies Record<Metric, Record<Period, string>>,
    emptyBody: "Counts arrive within seconds of each read, search or answer.",
    people: {
      off: "People are not ranked on this instance.",
      offBody:
        "An operator can turn the people leaderboard on. Even then, only people who chose to be shown appear: you can choose it now in",
      notOn: "You are not on this board.",
      notOnBody: "Only people who chose to be shown are ranked. To appear, turn it on in",
      interfaceLink: "Account → Interface",
      gone: "The people leaderboard was just turned off.",
    },
    failed: "Could not load the leaderboard.",
  },
  {
    title: "Ranking",
    description:
      "Co czytano, wyszukiwano i o co pytano najczęściej. Okresy w UTC; bieżący do teraz.",
    loading: "Wczytywanie rankingu…",
    controls: "Ranking",
    subject: "Kogo",
    metric: "Według",
    period: "Okres",
    subjects: { libraries: "Biblioteki", people: "Osoby" },
    metrics: {
      reads: "Odczyty",
      searches: "Wyszukiwania",
      answers: "Odpowiedzi agenta",
    },
    periods: {
      day: "Dzień",
      week: "Tydzień",
      month: "Miesiąc",
      year: "Rok",
    },
    value: {
      reads: (n) => plural.pl(n, { one: "# odczyt", few: "# odczyty", many: "# odczytów" }),
      searches: (n) =>
        plural.pl(n, { one: "# wyszukiwanie", few: "# wyszukiwania", many: "# wyszukiwań" }),
      answers: (n) =>
        plural.pl(n, { one: "# odpowiedź", few: "# odpowiedzi", many: "# odpowiedzi" }),
    },
    range: (start, end) => (start === end ? start : `${start} – ${end}`),
    top: "Pierwsza dziesiątka",
    item: (rank, name, value) => `${rank}. ${name}, ${value}`,
    you: "Ty",
    youSuffix: " (Ty)",
    movement: {
      up: (by, from) => `w górę o ${by} z #${from}`,
      down: (by, from) => `w dół o ${by} z #${from}`,
      same: (from) => `bez zmian, #${from}`,
      new: "nowość w tym okresie",
      newShort: "Nowe",
    },
    columns: {
      rank: "Miejsce",
      library: "Biblioteka",
      person: "Osoba",
      value: "Liczba",
      share: "Udział",
      change: "Zmiana",
    },
    shareOf: (name) => `Udział w okresie: ${name}`,
    rest: "Miejsca od 11.",
    find: "Znajdź w rankingu",
    findLibrary: "ID biblioteki",
    findPerson: "Nazwa użytkownika",
    noMatch: "Nikt w rankingu nie pasuje.",
    yourRank: (rank, value) => `Ty · #${rank} · ${value}`,
    empty: {
      reads: {
        day: "Dziś nic jeszcze nie przeczytano.",
        week: "W tym tygodniu nic jeszcze nie przeczytano.",
        month: "W tym miesiącu nic jeszcze nie przeczytano.",
        year: "W tym roku nic jeszcze nie przeczytano.",
      },
      searches: {
        day: "Dziś nie było jeszcze wyszukiwań.",
        week: "W tym tygodniu nie było jeszcze wyszukiwań.",
        month: "W tym miesiącu nie było jeszcze wyszukiwań.",
        year: "W tym roku nie było jeszcze wyszukiwań.",
      },
      answers: {
        day: "Dziś agent jeszcze nie odpowiadał.",
        week: "W tym tygodniu agent jeszcze nie odpowiadał.",
        month: "W tym miesiącu agent jeszcze nie odpowiadał.",
        year: "W tym roku agent jeszcze nie odpowiadał.",
      },
    },
    emptyBody: "Liczniki rosną kilka sekund po każdym odczycie, wyszukiwaniu lub odpowiedzi.",
    people: {
      off: "Ta instancja nie pokazuje rankingu osób.",
      offBody:
        "Operator może włączyć ranking osób. Nawet wtedy pojawiają się w nim tylko osoby, które się na to zgodziły: możesz to zrobić już teraz w",
      notOn: "Nie ma Cię w tym rankingu.",
      notOnBody: "W rankingu są tylko osoby, które się na to zgodziły. Aby się pojawić, włącz to w",
      interfaceLink: "Konto → Interfejs",
      gone: "Ranking osób został właśnie wyłączony.",
    },
    failed: "Nie udało się wczytać rankingu.",
  },
);
