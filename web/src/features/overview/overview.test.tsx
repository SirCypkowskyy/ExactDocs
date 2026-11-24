import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { OverviewPage, parseOverviewView } from "./index";
import { type AiUsage, budgetAlerts, firstDayOf, jobRows, peakOf } from "./model/overview";

const NOW = Date.parse("2026-11-24T12:00:00Z");

const library = (n: number, over: Record<string, unknown> = {}) => ({
  id: `/acme/lib${n}`,
  title: `Lib ${n}`,
  description: "",
  default_version: "v1",
  default_pinned: false,
  source_url: "https://example.com",
  refs: [],
  version_count: 2,
  tags: [],
  last_imported_at: null,
  logo: null,
  article_count: 40,
  ...over,
});

const zeroStates = { queued: 0, running: 0, succeeded: 0, failed: 0, cancelled: 0 };

/** Days from `from` to 2026-11-24; the last one (today) has 5 jobs, 2 of them failed. */
function jobDays(from: string) {
  const days = [];
  for (let t = Date.parse(`${from}T00:00:00Z`); t <= NOW; t += 86_400_000) {
    const day = new Date(t).toISOString().slice(0, 10);
    const today = day === "2026-11-24";
    days.push({
      day,
      total: today ? 5 : 1,
      by_state: today
        ? { ...zeroStates, succeeded: 3, failed: 2 }
        : { ...zeroStates, succeeded: 1 },
      by_kind: {},
    });
  }
  return days;
}

const budget = (over: Record<string, unknown> = {}) => ({
  window: "month",
  window_start: "2026-11-01",
  resets_at: "2026-12-01T00:00:00Z",
  usd_limit: 50,
  usd_left: 4,
  tokens_limit: null,
  tokens_left: null,
  reached: false,
  own_usd_limit: null,
  own_tokens_limit: null,
  ...over,
});

const spent = (usd: number) => ({
  input_tokens: 0,
  output_tokens: 0,
  tokens: 0,
  local_tokens: 0,
  requests: 1,
  usd,
  unpriced_requests: 0,
});

interface Options {
  failing?: number;
  budgets?: boolean;
  jobsFail?: boolean;
}

function serve({ failing = 7, budgets = true, jobsFail = false }: Options = {}) {
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(String(input), "http://x");
    const p = url.pathname;
    const q = url.searchParams;
    if (p === "/api/v1/libraries" && q.get("sync_state")) {
      return Response.json({
        notice: "",
        libraries: failing ? [library(9, { logo: null })] : [],
        next_cursor: null,
        total: failing,
      });
    }
    if (p === "/api/v1/libraries") {
      return Response.json({
        notice: "",
        libraries: [library(1), library(2), library(3, { version_count: 1, article_count: 40 })],
        next_cursor: null,
        total: 3,
      });
    }
    if (p === "/api/v1/stats/jobs") {
      if (jobsFail) return Response.json({ error: "unexpected" }, { status: 500 });
      const from = q.get("from") ?? "2026-10-26";
      return Response.json({ bucket: "day", from, to: "2026-11-24", days: jobDays(from) });
    }
    if (p === "/api/v1/ai/usage/history") {
      return Response.json({
        scope: "instance",
        id: "",
        window: "day",
        first: q.get("from"),
        last: "2026-11-24",
        entries: [
          { window_start: "2026-11-23", ...spent(1.5) },
          { window_start: "2026-11-24", ...spent(0.25) },
        ],
      });
    }
    if (p === "/api/v1/stats/usage" && q.get("period") === "week") {
      return Response.json({
        period: "week",
        since: "2026-11-23",
        until: "2026-11-29",
        by: "none",
        total: { reads: 1234, searches: 56, answers: 1 },
        series: [],
        groups: [],
        groups_total: 0,
      });
    }
    if (p === "/api/v1/stats/usage") {
      return Response.json({
        period: "day",
        since: "2026-11-23",
        until: "2026-11-24",
        by: "library",
        total: { reads: 30, searches: 4, answers: 0 },
        series: [
          { start: "2026-11-23", end: "2026-11-23", reads: 10, searches: 1, answers: 0 },
          { start: "2026-11-24", end: "2026-11-24", reads: 20, searches: 3, answers: 0 },
        ],
        groups: [
          { library: "/acme/lib1", reads: 18, searches: 0, answers: 0, others: false },
          { library: null, reads: 0, searches: 4, answers: 0, others: false },
        ],
        groups_total: 2,
      });
    }
    if (p === "/api/v1/ai/usage") {
      return Response.json({
        at: "2026-11-24T12:00:00Z",
        llm_searches_per_minute: null,
        scopes: [
          {
            scope: "instance",
            id: "",
            day: spent(0.25),
            month: spent(46),
            budgets: budgets ? [budget()] : [],
          },
        ],
      });
    }
    return Response.json({ error: "not_found" }, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const urls = (fetchMock: ReturnType<typeof serve>, path: string) =>
  fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.startsWith(`/api/v1${path}`));

/**
 * A link's search as the app writes it. The test router keeps TanStack's JSON for lists
 * (`["failed"]`) where the app's router writes `failed` (table-search.ts): both read the same.
 */
function linkSearch(link: HTMLElement): Record<string, string> {
  const params = new URL(link.getAttribute("href") ?? "", "http://x").searchParams;
  return Object.fromEntries(
    [...params].map(([k, v]) => [k, v.startsWith("[") ? (JSON.parse(v) as string[]).join(",") : v]),
  );
}

function renderPage(start = "/overview") {
  const history = createMemoryHistory({ initialEntries: [start] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <TestRouter
          history={history}
          pages={{
            "/overview": OverviewPage,
            "/jobs": () => <p>Jobs page</p>,
            "/ai": () => <p>AI page</p>,
            "/libraries/$owner/$repo": () => <p>Library page</p>,
          }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  resetPreferences();
});

describe("the overview's view and figures", () => {
  it("keeps only a range it offers in the URL, 30 days being the default", () => {
    expect(parseOverviewView({ days: "7" })).toEqual({ days: 7 });
    expect(parseOverviewView({ days: 90 })).toEqual({ days: 90 });
    expect(parseOverviewView({ days: "30" })).toEqual({ days: undefined });
    expect(parseOverviewView({ days: "365" })).toEqual({ days: undefined });
    expect(firstDayOf(7, NOW)).toBe("2026-11-18");
  });

  it("finds the busiest day and the budgets near their ceiling", () => {
    const rows = jobRows({
      bucket: "day",
      from: "2026-11-23",
      to: "2026-11-24",
      days: jobDays("2026-11-23"),
    });
    expect(rows.at(-1)).toMatchObject({ day: "2026-11-24", succeeded: 3, failed: 2 });
    expect(peakOf(rows, "failed")?.day).toBe("2026-11-24");
    expect(peakOf(rows, "running")).toBeUndefined();
    const usage = (b: Record<string, unknown>): AiUsage => ({
      at: "",
      llm_searches_per_minute: null,
      scopes: [
        {
          scope: "library",
          id: "/a/b",
          day: spent(0),
          month: spent(0),
          budgets: [budget(b) as AiUsage["scopes"][number]["budgets"][number]],
        },
      ],
    });
    expect(budgetAlerts(usage({ usd_left: 4 }))).toEqual([
      { scope: "library", id: "/a/b", window: "month", used: 92, reached: false },
    ]);
    expect(budgetAlerts(usage({ usd_left: 30 }))).toEqual([]);
    expect(budgetAlerts(usage({ reached: true, usd_left: 0 }))[0]?.reached).toBe(true);
  });
});

describe("the overview page", () => {
  it("shows the instance's figures in tiles", async () => {
    serve();
    renderPage();
    const tiles = await screen.findByRole("list", { name: "Instance figures" });
    expect(await within(tiles).findByText("5 versions · 120 articles")).toBeInTheDocument();
    expect(within(tiles).getByText("3")).toBeInTheDocument();
    const failed = await within(tiles).findByRole("link", {
      name: "2 failed. Show failed jobs from the last 24 hours",
    });
    expect(linkSearch(failed)).toEqual({ state: "failed", created: "24h" });
    expect(within(tiles).getByText("$46.00")).toBeInTheDocument();
    expect(within(tiles).getByText("of a $50.00 monthly budget")).toBeInTheDocument();
    expect(within(tiles).getByRole("meter", { name: "Monthly AI budget used" })).toHaveAttribute(
      "aria-valuenow",
      "92",
    );
    expect(within(tiles).getByText("1,234")).toBeInTheDocument();
    expect(within(tiles).getByText("56 searches · 1 answer")).toBeInTheDocument();
  });

  it("draws each chart as a described picture and shows the same numbers as a table", async () => {
    serve();
    renderPage();
    const card = (await screen.findByRole("heading", { name: "AI spend per day" })).closest(
      "section",
    ) as HTMLElement;
    expect(await within(card).findByText("$1.75")).toBeInTheDocument();
    const picture = within(card).getByRole("img", { name: "AI spend per day" });
    expect(picture).toHaveAccessibleDescription("$1.75 spent in the last 30 days, most on Nov 23.");

    const toggle = within(card).getByRole("button", { name: "Show as table" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    const table = within(card).getByRole("table", { name: "AI spend per day" });
    expect(within(table).getByRole("rowheader", { name: "Nov 23" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "$1.50" })).toBeInTheDocument();
    expect(within(card).queryByRole("img")).not.toBeInTheDocument();

    const jobs = screen
      .getByRole("heading", { name: "Jobs per day" })
      .closest("section") as HTMLElement;
    expect(await within(jobs).findByText("34 jobs")).toBeInTheDocument();
    expect(within(jobs).getByText("Failed")).toBeInTheDocument();
    const reads = screen
      .getByRole("heading", { name: "Docs read per day" })
      .closest("section") as HTMLElement;
    expect(await within(reads).findByText("30 reads")).toBeInTheDocument();
  });

  it("lists the most-read libraries", async () => {
    serve();
    renderPage();
    const top = (await screen.findByRole("heading", { name: "Most-read libraries" })).closest(
      "section",
    ) as HTMLElement;
    expect(await within(top).findByRole("link", { name: "/acme/lib1" })).toBeInTheDocument();
    expect(within(top).getByText("18 reads")).toBeInTheDocument();
    // Searches over several libraries read nothing: they are not a library on this list.
    expect(within(top).getAllByRole("listitem")).toHaveLength(1);
  });

  it("says what needs attention: failed syncs and budgets near their limit", async () => {
    serve();
    renderPage();
    const section = (await screen.findByRole("heading", { name: /Needs attention/ })).closest(
      "section",
    ) as HTMLElement;
    const jobs = await within(section).findByRole("link", { name: "Failed jobs of /acme/lib9" });
    expect(linkSearch(jobs)).toEqual({ library: "/acme/lib9", state: "failed" });
    expect(within(section).getByText("and 6 more libraries")).toBeInTheDocument();
    expect(
      within(section).getByText("Instance: 92% of the monthly budget used"),
    ).toBeInTheDocument();
    expect(
      within(section).getByRole("meter", { name: "Budget used: Instance" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Needs attention/ })).toHaveTextContent("8");
  });

  it("says when nothing needs attention", async () => {
    serve({ failing: 0, budgets: false });
    renderPage();
    expect(await screen.findByText("Nothing needs attention.")).toBeInTheDocument();
    expect(await screen.findByText("No monthly budget set")).toBeInTheDocument();
  });

  it("keeps the range in the URL and asks for that range", async () => {
    const fetchMock = serve();
    const history = renderPage("/overview?days=7");
    const range = await screen.findByRole("radiogroup", { name: "Chart range" });
    expect(within(range).getByRole("radio", { name: "7 days" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await waitFor(() =>
      expect(urls(fetchMock, "/stats/jobs")).toContain(
        "/api/v1/stats/jobs?bucket=day&from=2026-11-18",
      ),
    );
    expect(urls(fetchMock, "/stats/usage")).toContain(
      "/api/v1/stats/usage?period=day&periods=7&by=library&limit=5",
    );
    expect(urls(fetchMock, "/ai/usage/history")).toContain(
      "/api/v1/ai/usage/history?scope=instance&window=day&from=2026-11-18",
    );

    await userEvent.click(within(range).getByRole("radio", { name: "90 days" }));
    await waitFor(() => expect(history.location.search).toContain("days=90"));
    await waitFor(() =>
      expect(urls(fetchMock, "/stats/jobs")).toContain(
        "/api/v1/stats/jobs?bucket=day&from=2026-08-27",
      ),
    );
    await userEvent.click(within(range).getByRole("radio", { name: "30 days" }));
    await waitFor(() => expect(history.location.search).not.toContain("days="));
  });

  it("says inside the card when a chart failed, and tries again", async () => {
    const fetchMock = serve({ jobsFail: true });
    renderPage();
    const jobs = (await screen.findByRole("heading", { name: "Jobs per day" })).closest(
      "section",
    ) as HTMLElement;
    expect(await within(jobs).findByRole("alert")).toHaveTextContent("Could not load this chart.");
    const asked = urls(fetchMock, "/stats/jobs").length;
    await userEvent.click(within(jobs).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(urls(fetchMock, "/stats/jobs").length).toBeGreaterThan(asked));
    // The other blocks still show what they have.
    expect(await screen.findByText("5 versions · 120 articles")).toBeInTheDocument();
  });

  it("speaks Polish", async () => {
    setPreferences({ language: "pl" });
    serve();
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "Przegląd" })).toBeInTheDocument();
    const tiles = screen.getByRole("list", { name: "Liczby instancji" });
    expect(await within(tiles).findByText("5 wersji · 120 artykułów")).toBeInTheDocument();
    expect(await within(tiles).findByText("2 nieudane")).toBeInTheDocument();
    expect(within(tiles).getByText("56 wyszukiwań · 1 odpowiedź")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "7 dni" })).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Wydatki na AI dziennie" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("i 6 innych bibliotek")).toBeInTheDocument();
    expect(
      screen.getByText("Instancja: wykorzystano 92% miesięcznego budżetu"),
    ).toBeInTheDocument();
  });
});
