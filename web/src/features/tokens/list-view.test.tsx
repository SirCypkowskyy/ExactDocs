import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { TokensSection } from "./index";
import { expiryOf, lastUseOf, parseTokensView, scopeOf } from "./model/list-view";

const NOW = Date.parse("2026-11-20T12:00:00Z");
const DAY = 86_400_000;
const at = (days: number) => new Date(NOW + days * DAY).toISOString();

const token = (name: string, over: Record<string, unknown> = {}) => ({
  id: name,
  name,
  prefix: `exd_${name.slice(0, 4)}`,
  created_at: "2026-11-13T10:00:00Z",
  expires_at: null,
  last_used_at: null,
  library_ids: null,
  ...over,
});

/** Four tokens: one used lately and expiring soon, one expired, one scoped, one never used. */
const TOKENS = [
  token("laptop", { expires_at: at(3), last_used_at: at(-1), created_at: at(-20) }),
  token("ci-main", { expires_at: at(-2), last_used_at: at(-40), created_at: at(-30) }),
  token("ci-nightly", { library_ids: ["/acme/api"], expires_at: at(60), created_at: at(-10) }),
  token("desk", { library_ids: [], created_at: at(-5) }),
];

function serve() {
  const fetchMock = vi.fn(async (_url: string) =>
    Response.json({ tokens: TOKENS, next_cursor: null, total: TOKENS.length }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderSection(start = "/account") {
  const history = createMemoryHistory({ initialEntries: [start] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TestRouter history={history} pages={{ "/account": TokensSection }} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

const names = () =>
  within(screen.getByRole("table", { name: "API tokens" }))
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getByRole("rowheader").textContent);

describe("the token table", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("keeps only what the table knows from a hand-edited URL", () => {
    expect(
      parseTokensView({
        q: " ci ",
        sort: "-used",
        expires: "soon,never",
        used: "lately",
        size: 100,
        x: 1,
      }),
    ).toEqual({
      q: "ci",
      sort: "-used",
      page: undefined,
      // A list of at most 50 offers no page of 100.
      size: undefined,
      libraries: undefined,
      expires: ["soon", "never"],
      used: undefined,
    });
  });

  it("sorts each token into its scope, expiry and use", () => {
    const [laptop, ciMain, ciNightly, desk] = TOKENS as [
      (typeof TOKENS)[0],
      (typeof TOKENS)[0],
      (typeof TOKENS)[0],
      (typeof TOKENS)[0],
    ];
    expect([laptop, ciNightly, desk].map(scopeOf)).toEqual(["all", "some", "none"]);
    expect([laptop, ciMain, ciNightly, desk].map((t) => expiryOf(t, NOW))).toEqual([
      "soon",
      "expired",
      "later",
      "never",
    ]);
    expect([laptop, ciMain, desk].map((t) => lastUseOf(t, NOW))).toEqual([
      "recent",
      "older",
      "never",
    ]);
  });

  it("asks once, newest first, and searches names in the browser", async () => {
    const fetchMock = serve();
    const history = renderSection();
    await screen.findByText("1–4 of 4");
    expect(names()).toEqual(["desk", "ci-nightly", "laptop", "ci-main"]);

    await userEvent.type(screen.getByRole("searchbox", { name: "Find a token" }), "ci");

    expect(await screen.findByText("1–2 of 2")).toBeInTheDocument();
    expect(history.location.search).toContain("q=ci");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/tokens?limit=50");
  });

  it("sorts by expiry with the tokens that never expire first", async () => {
    serve();
    const history = renderSection();
    await screen.findByText("1–4 of 4");

    await userEvent.click(screen.getByRole("button", { name: "Sort by Expires" }));

    await waitFor(() => expect(names()).toEqual(["desk", "ci-main", "laptop", "ci-nightly"]));
    expect(history.location.search).toContain("sort=expires");
  });

  it("filters by expiry with counts, and says when nothing matches", async () => {
    serve();
    const history = renderSection();
    await screen.findByText("1–4 of 4");

    await userEvent.click(screen.getByRole("button", { name: "Expires" }));
    const soon = await screen.findByRole("option", { name: /Expires within 7 days/ });
    expect(soon).toHaveTextContent("1");
    await userEvent.click(soon);
    await userEvent.keyboard("{Escape}");

    expect(await screen.findByText("1–1 of 1")).toBeInTheDocument();
    expect(names()).toEqual(["laptop"]);
    expect(history.location.search).toContain("expires=soon");

    await userEvent.type(screen.getByRole("searchbox", { name: "Find a token" }), "desk");
    expect(await screen.findByText("No tokens match")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("1–4 of 4")).toBeInTheDocument();
    expect(history.location.search).toBe("");
  });

  it("names a search that matches nothing", async () => {
    serve();
    renderSection("/account?q=zzz");
    expect(await screen.findByText("No tokens match")).toBeInTheDocument();
    expect(screen.getByText("No token name contains “zzz”.")).toBeInTheDocument();
    expect(screen.queryByText(/no tokens yet/i)).not.toBeInTheDocument();
  });

  it("shows expiry, last use and scope the way they read best", async () => {
    serve();
    renderSection();
    await screen.findByText("1–4 of 4");
    const row = (name: string) =>
      screen.getByRole("rowheader", { name: new RegExp(`^${name}$`) }).closest("tr") as HTMLElement;
    expect(within(row("laptop")).getByText("in 3 days")).toBeInTheDocument();
    expect(within(row("ci-main")).getByText("Expired")).toBeInTheDocument();
    expect(row("desk")).toHaveTextContent("No libraries");
    expect(row("desk")).toHaveTextContent("No expiry");
    expect(row("desk")).toHaveTextContent("Never used");
    expect(within(row("ci-nightly")).getByText("/acme/api")).toBeInTheDocument();
    expect(row("laptop")).toHaveTextContent("All libraries you can access");
    expect(
      within(row("laptop")).getByRole("button", { name: "Copy token prefix" }),
    ).toBeInTheDocument();
  });
});
