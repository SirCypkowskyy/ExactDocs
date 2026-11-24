import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { LeaderboardPage, parseLeaderboardView } from "./index";
import { boardOf, movementOf } from "./model/leaderboard";

type Entry = {
  rank: number;
  previous_rank: number | null;
  value: number;
  library?: string | null;
  account_id?: string | null;
  username?: string | null;
  you: boolean;
};

/** `count` libraries, 10 reads apart; #2 was #4, #3 was #2, #4 is new, the rest kept their rank. */
const libraries = (count: number, metric = "reads"): Entry[] =>
  Array.from({ length: count }, (_, i) => ({
    rank: i + 1,
    previous_rank: i === 1 ? 4 : i === 2 ? 2 : i === 3 ? null : i + 1,
    value: (metric === "reads" ? 300 : 100) - i * 10,
    library: `/acme/lib${i + 1}`,
    you: false,
  }));

const people = (): Entry[] => [
  { rank: 1, previous_rank: 1, value: 50, account_id: "a1", username: "alice", you: false },
  { rank: 2, previous_rank: null, value: 20, account_id: "a2", username: "bob", you: true },
];

interface Options {
  peopleOn?: boolean;
  entries?: Entry[];
  peopleEntries?: Entry[];
  you?: Entry | null;
}

function serve({ peopleOn = false, entries, peopleEntries = people(), you = null }: Options = {}) {
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(String(input), "http://x");
    if (url.pathname === "/api/v1/stats/settings") {
      return Response.json({ people_leaderboard: peopleOn, retention_months: 13 });
    }
    if (url.pathname === "/api/v1/stats/leaderboard") {
      const subject = url.searchParams.get("subject") ?? "libraries";
      const metric = url.searchParams.get("metric") ?? "reads";
      if (subject === "people" && !peopleOn) {
        return Response.json({ error: "people_leaderboard_off" }, { status: 403 });
      }
      const list = subject === "people" ? peopleEntries : (entries ?? libraries(15, metric));
      return Response.json({
        subject,
        metric,
        period: url.searchParams.get("period") ?? "week",
        start: "2026-11-23",
        end: "2026-11-29",
        previous_start: "2026-11-16",
        previous_end: "2026-11-22",
        total: list.reduce((sum, e) => sum + e.value, 0),
        ranked: list.length,
        entries: list,
        you: subject === "people" ? you : null,
      });
    }
    return Response.json({ error: "not_found" }, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const boards = (fetchMock: ReturnType<typeof serve>) =>
  fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/stats/leaderboard"));

function renderPage(start = "/leaderboard") {
  const history = createMemoryHistory({ initialEntries: [start] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <TestRouter
          history={history}
          pages={{
            "/leaderboard": LeaderboardPage,
            "/account": () => <p>Account page</p>,
            "/libraries/$owner/$repo": () => <p>Library page</p>,
          }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

const animate = vi.fn();

beforeEach(() => {
  animate.mockClear();
  // jsdom has no Web Animations; the columns grow in with it on first show.
  Element.prototype.animate = animate as unknown as Element["animate"];
});
afterEach(() => {
  vi.unstubAllGlobals();
  resetPreferences();
  delete (Element.prototype as Partial<Element>).animate;
});

describe("the leaderboard's model", () => {
  it("keeps only a board it offers in the URL, defaults left out", () => {
    expect(
      parseLeaderboardView({ subject: "people", metric: "answers", period: "year", page: "2" }),
    ).toMatchObject({ subject: "people", metric: "answers", period: "year", page: 2 });
    expect(
      parseLeaderboardView({ subject: "libraries", metric: "reads", period: "week" }),
    ).toMatchObject({ subject: undefined, metric: undefined, period: undefined });
    expect(parseLeaderboardView({ subject: "robots", period: "decade" })).toMatchObject({
      subject: undefined,
      period: undefined,
    });
    // People only while the operator has the people board on.
    expect(boardOf({ subject: "people" }, false).subject).toBe("libraries");
    expect(boardOf({ subject: "people" }, true)).toEqual({
      subject: "people",
      metric: "reads",
      period: "week",
    });
  });

  it("tells a move up, down, none and a newcomer apart", () => {
    const e = (rank: number, previous_rank: number | null) => ({
      rank,
      previous_rank,
      value: 1,
      you: false,
    });
    expect(movementOf(e(2, 5))).toEqual({ kind: "up", by: 3, from: 5 });
    expect(movementOf(e(4, 1))).toEqual({ kind: "down", by: 3, from: 1 });
    expect(movementOf(e(3, 3))).toEqual({ kind: "same", from: 3 });
    expect(movementOf(e(3, null))).toEqual({ kind: "new" });
  });
});

describe("the leaderboard page", () => {
  it("shows the top ten as columns that read as a list, and ranks 11 and up in a table", async () => {
    serve();
    renderPage();
    const top = await screen.findByRole("list", { name: "Top ten" });
    const items = within(top).getAllByRole("listitem");
    expect(items).toHaveLength(10);
    expect(
      within(top).getByRole("link", { name: "2. /acme/lib2, 290 reads, up 2 from #4" }),
    ).toHaveAttribute("href", "/libraries/acme/lib2");
    expect(within(top).getByRole("link", { name: "3. /acme/lib3, 280 reads, down 1 from #2" }));
    expect(within(top).getByRole("link", { name: "4. /acme/lib4, 270 reads, new this period" }));

    // The fills scale from the bottom against the top value, staggered 30 ms.
    const fills = top.querySelectorAll<HTMLElement>("[data-slot=leaderboard-fill]");
    expect(fills[0]?.style.transform).toBe("scaleY(1)");
    expect(fills[2]?.style.transform).toBe("scaleY(0.933333)");
    expect(fills[2]?.style.transitionDelay).toBe("60ms");
    expect(fills[0]).toHaveClass("origin-bottom", "bg-chart-series");
    // First show: each fill grows in from 0 (transform only), one after another.
    expect(animate).toHaveBeenCalledTimes(10);
    expect(animate.mock.calls[0]?.[0]).toEqual([{ transform: "scaleY(0)", offset: 0 }]);
    expect(animate.mock.calls[3]?.[1]).toMatchObject({ delay: 90 });

    const table = screen.getByRole("table", { name: "Ranks 11 and up" });
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((c) => c.textContent),
    ).toEqual(["/acme/lib11", "/acme/lib12", "/acme/lib13", "/acme/lib14", "/acme/lib15"]);
    const row = within(table).getByRole("rowheader", { name: "/acme/lib11" }).closest("tr");
    expect(within(row as HTMLElement).getByText("same as before, #11")).toBeInTheDocument();
    expect(screen.getByText(/Week: Nov 23, 2026 – Nov 29, 2026/)).toBeInTheDocument();
  });

  it("switches metric and period in the URL, keeping the columns while the next board loads", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByRole("list", { name: "Top ten" });
    expect(boards(fetchMock)).toEqual([
      "/api/v1/stats/leaderboard?subject=libraries&metric=reads&period=week&limit=100",
    ]);
    const first = screen.getByRole("link", { name: /^1\. \/acme\/lib1/ }).closest("li");

    await userEvent.click(screen.getByRole("radio", { name: "Searches" }));
    await waitFor(() => expect(history.location.search).toContain("metric=searches"));
    expect(
      await screen.findByRole("link", { name: /^1\. \/acme\/lib1, 100 searches/ }),
    ).toBeInTheDocument();
    // The same library keeps its column (keyed by library), so it moves from where it was.
    expect(screen.getByRole("link", { name: /^1\. \/acme\/lib1/ }).closest("li")).toBe(first);

    await userEvent.click(screen.getByRole("radio", { name: "Month" }));
    await waitFor(() => expect(history.location.search).toContain("period=month"));
    expect(boards(fetchMock).at(-1)).toBe(
      "/api/v1/stats/leaderboard?subject=libraries&metric=searches&period=month&limit=100",
    );
    await userEvent.click(screen.getByRole("radio", { name: "Week" }));
    await waitFor(() => expect(history.location.search).not.toContain("period="));
  });

  it("does not move the columns under reduced motion", async () => {
    setPreferences({ motion: "reduced" });
    serve();
    renderPage();
    const top = await screen.findByRole("list", { name: "Top ten" });
    expect(animate).not.toHaveBeenCalled();
    expect(top.querySelector("[data-slot=leaderboard-fill]")).toHaveClass(
      "motion-reduce:transition-none",
    );
  });

  it("shows no people while the operator has the people board off, and says how to opt in", async () => {
    const fetchMock = serve();
    renderPage("/leaderboard?subject=people");
    await screen.findByRole("list", { name: "Top ten" });
    expect(screen.queryByRole("radiogroup", { name: "Ranked" })).not.toBeInTheDocument();
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("People are not ranked on this instance.");
    expect(within(note).getByRole("link", { name: "Account → Interface" })).toHaveAttribute(
      "href",
      "/account?tab=interface",
    );
    expect(boards(fetchMock).every((u) => u.includes("subject=libraries"))).toBe(true);
  });

  it("ranks people who opted in when the board is on, and lights up you", async () => {
    serve({ peopleOn: true });
    renderPage("/leaderboard?subject=people");
    const top = await screen.findByRole("list", { name: "Top ten" });
    expect(within(top).getByText("1. alice, 50 reads, same as before, #1")).toBeInTheDocument();
    const mine = within(top).getByText("2. bob, 20 reads (you), new this period").closest("li");
    expect(mine?.querySelector("[data-slot=leaderboard-fill]")).toHaveClass("bg-chart-highlight");
    expect(within(mine as HTMLElement).getByText("You")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "People" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    // Two people: nobody past ten, so no table.
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("tells people who are not on the board how to be, and where they rank past the list", async () => {
    serve({
      peopleOn: true,
      peopleEntries: [people()[0] as Entry],
      you: { rank: 123, previous_rank: null, value: 4, username: "bob", you: true },
    });
    renderPage("/leaderboard?subject=people");
    await screen.findByRole("list", { name: "Top ten" });
    expect(screen.getByText("You · #123 · 4 reads")).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("asks people who did not opt in to do so", async () => {
    serve({ peopleOn: true, peopleEntries: [people()[0] as Entry] });
    renderPage("/leaderboard?subject=people");
    await screen.findByRole("list", { name: "Top ten" });
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("You are not on this board.");
    expect(within(note).getByRole("link", { name: "Account → Interface" })).toBeInTheDocument();
  });

  it("says when nothing was counted yet", async () => {
    serve({ entries: [] });
    renderPage("/leaderboard?metric=answers&period=day");
    expect(await screen.findByText("No agent answers today yet.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Top ten" })).not.toBeInTheDocument();
  });

  it("speaks Polish", async () => {
    setPreferences({ language: "pl" });
    serve();
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "Ranking" })).toBeInTheDocument();
    const top = await screen.findByRole("list", { name: "Pierwsza dziesiątka" });
    expect(
      within(top).getByRole("link", { name: "2. /acme/lib2, 290 odczytów, w górę o 2 z #4" }),
    ).toBeInTheDocument();
    expect(
      within(top).getByRole("link", { name: "4. /acme/lib4, 270 odczytów, nowość w tym okresie" }),
    );
    expect(screen.getByRole("radio", { name: "Odpowiedzi agenta" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Miejsca od 11." })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Ta instancja nie pokazuje rankingu osób.");
  });
});
