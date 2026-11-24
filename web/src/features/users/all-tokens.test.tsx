import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { AllTokensPage, parseAllTokensView } from "./index";
import { allTokensFilters, allTokensParams } from "./model/all-tokens-view";

const DAY = 86_400_000;
const at = (days: number) => new Date(Date.now() + days * DAY).toISOString();

/** Token `n`: alice holds the odd ones, bob the even ones; token 1 expired, token 2 was never used. */
const token = (n: number) => ({
  id: `t${n}`,
  name: `token ${String(n).padStart(2, "0")}`,
  prefix: `exd_ab${String(n).padStart(2, "0")}`,
  created_at: at(-n),
  expires_at: n === 1 ? at(-1) : n === 3 ? at(3) : n === 4 ? null : at(60),
  last_used_at: n === 2 ? null : at(-0.5),
  library_ids: n === 1 ? ["/acme/payments", "/acme/ledger", "/acme/web"] : null,
  owner_id: n % 2 ? "ua" : "ub",
  owner: n % 2 ? "alice" : "bob",
});

/**
 * Every account's tokens behind an API that filters by `owner_id`, `expired` and `unused` and
 * pages with `limit` and an `offset` (or a cursor, `o<n>`).
 */
function serve(count = 25) {
  const all = Array.from({ length: count }, (_, i) => token(i + 1));
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(String(input), "http://x");
    const owner = url.searchParams.get("owner_id");
    const expired = url.searchParams.get("expired");
    const unused = url.searchParams.get("unused");
    const rows = all.filter(
      (t) =>
        (!owner || t.owner_id === owner) &&
        (expired === null ||
          (t.expires_at !== null && Date.parse(t.expires_at) < Date.now()) ===
            (expired === "true")) &&
        (unused === null || (t.last_used_at === null) === (unused === "true")),
    );
    const start = Number(
      url.searchParams.get("offset") ?? url.searchParams.get("cursor")?.slice(1) ?? 0,
    );
    const limit = Number(url.searchParams.get("limit"));
    return Response.json({
      tokens: rows.slice(start, start + limit),
      next_cursor: start + limit < rows.length ? `o${start + limit}` : null,
      total: rows.length,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const urls = (fetchMock: ReturnType<typeof serve>) =>
  fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/v1/users/tokens?"));

function renderPage(start = "/users/tokens") {
  const history = createMemoryHistory({ initialEntries: [start] });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TestRouter
          history={history}
          pages={{
            "/users/tokens": AllTokensPage,
            "/users": () => <p>Accounts</p>,
            "/access-log": () => <p>Access log</p>,
          }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

/** The table's row of a token. */
async function rowOf(name: string): Promise<HTMLElement> {
  const table = await screen.findByRole("table", {
    name: /API tokens of every account|Tokeny API wszystkich kont/,
  });
  const row = (await within(table).findByText(name)).closest("tr");
  if (!row) throw new Error(`no row for ${name}`);
  return row;
}

describe("every account's API tokens", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("keeps only what the API knows from a hand-edited URL", () => {
    expect(
      parseAllTokensView({
        q: " ci ",
        owner: "0190abcd",
        expiry: "expired",
        use: "unused",
        sort: "owner",
        page: 2,
      }),
    ).toEqual({
      q: "ci",
      owner: "0190abcd",
      expiry: "expired",
      use: "unused",
      sort: "owner",
      page: 2,
      size: undefined,
    });
    expect(parseAllTokensView({ owner: "a b", expiry: "soon", use: "x", sort: "secret" })).toEqual({
      q: undefined,
      sort: undefined,
      page: undefined,
      size: undefined,
      owner: undefined,
      expiry: undefined,
      use: undefined,
    });
    expect(
      allTokensParams(
        allTokensFilters({ q: "ci", owner: "ua", expiry: "valid", use: "used", sort: "-name" }),
        20,
        "c1",
      ),
    ).toBe("limit=20&q=ci&owner_id=ua&expired=false&unused=false&sort=-name&cursor=c1");
    expect(allTokensParams({}, 20, "c1", 40)).toBe("limit=20&offset=40");
  });

  it("lists each token with its owner, prefix, libraries, expiry and last use", async () => {
    const fetchMock = serve();
    renderPage();
    expect(await screen.findByText("1–20 of 25")).toBeInTheDocument();
    expect(screen.getByText("25 tokens")).toHaveAttribute("role", "status");
    expect(urls(fetchMock)[0]).toBe("/api/v1/users/tokens?limit=20&offset=0");
    expect(screen.getByRole("heading", { level: 1, name: "Users" })).toBeInTheDocument();
    expect(document.title).toBe("All API tokens - ExactDocs");
    const views = screen.getByRole("navigation", { name: "Users views" });
    expect(within(views).getByRole("link", { name: "API tokens" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(views).getByRole("link", { name: "Accounts" })).toHaveAttribute("href", "/users");

    const one = within(await rowOf("token 01"));
    expect(one.getByText("alice")).toBeInTheDocument();
    expect(one.getByText("exd_ab01…")).toBeInTheDocument();
    expect(one.getByRole("button", { name: "Copy token prefix" })).toBeInTheDocument();
    expect(one.getByText("Expired")).toBeInTheDocument();
    expect(one.getByText("/acme/payments")).toBeInTheDocument();
    expect(within(await rowOf("token 02")).getAllByText("Never")).toHaveLength(1);
    expect(within(await rowOf("token 02")).getByText("All their libraries")).toBeInTheDocument();
    expect(within(await rowOf("token 03")).getByText("in 2 days")).toBeInTheDocument();
    expect(within(await rowOf("token 04")).getByText("Never")).toBeInTheDocument();
  });

  it("filters by expiry, use and name on the server, in the URL", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 25");

    await userEvent.click(screen.getByRole("button", { name: "Expiry" }));
    await userEvent.click(await screen.findByRole("option", { name: "Expired" }));
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/users/tokens?limit=20&expired=true&offset=0"),
    );
    expect(await screen.findByText("1–1 of 1")).toBeInTheDocument();
    expect(history.location.search).toContain("expiry=expired");

    await userEvent.click(screen.getByRole("button", { name: "Expiry, 1 selected" }));
    await userEvent.click(await screen.findByRole("option", { name: "Still valid" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Use" }));
    await userEvent.click(await screen.findByRole("option", { name: "Never used" }));
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(urls(fetchMock)).toContain(
        "/api/v1/users/tokens?limit=20&expired=false&unused=true&offset=0",
      ),
    );
    expect(history.location.search).toContain("use=unused");

    await userEvent.type(screen.getByLabelText("Find a token"), "deploy");
    await waitFor(() =>
      expect(urls(fetchMock)).toContain(
        "/api/v1/users/tokens?limit=20&q=deploy&expired=false&unused=true&offset=0",
      ),
    );
  });

  it("sorts by owner on the server and pages by offset", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 25");
    expect(screen.getByRole("columnheader", { name: /Created/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );

    await userEvent.click(screen.getByRole("button", { name: "Sort by Owner" }));
    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/users/tokens?limit=20&sort=owner&offset=0"),
    );
    expect(history.location.search).toContain("sort=owner");

    await userEvent.click(screen.getByRole("button", { name: "Last page" }));
    expect(await screen.findByText("21–25 of 25")).toBeInTheDocument();
    expect(urls(fetchMock)).toContain("/api/v1/users/tokens?limit=20&sort=owner&offset=20");
    expect(urls(fetchMock).every((u) => !u.includes("cursor="))).toBe(true);
  });

  it("narrows to one person's tokens from a row, naming them in the chip", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 25");

    await userEvent.click(screen.getByRole("button", { name: "More actions for token 02 (bob)" }));
    const menu = await screen.findByRole("menu");
    // Operators cannot revoke someone's token here: the API offers no such call.
    expect(within(menu).queryByRole("menuitem", { name: /Revoke/ })).not.toBeInTheDocument();
    await userEvent.click(
      within(menu).getByRole("menuitem", { name: "Show this person's tokens" }),
    );

    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/users/tokens?limit=20&owner_id=ub&offset=0"),
    );
    expect(history.location.search).toContain("owner=ub");
    const chips = await screen.findByRole("list", { name: "Active filters" });
    expect(await within(chips).findByText("bob")).toBeInTheDocument();
    expect(await screen.findByText("1–12 of 12")).toBeInTheDocument();
  });

  it("reads the owner from a link, and leads to their access-log entries", async () => {
    const fetchMock = serve();
    const history = renderPage("/users/tokens?owner=ua");
    expect(await screen.findByText("1–13 of 13")).toBeInTheDocument();
    expect(urls(fetchMock)[0]).toBe("/api/v1/users/tokens?limit=20&owner_id=ua&offset=0");

    await userEvent.click(
      screen.getByRole("button", { name: "More actions for token 01 (alice)" }),
    );
    const menu = await screen.findByRole("menu");
    expect(
      within(menu).queryByRole("menuitem", { name: "Show this person's tokens" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      within(menu).getByRole("menuitem", { name: "Show their access-log entries" }),
    );
    expect(await screen.findByText("Access log")).toBeInTheDocument();
    expect(history.location.search).toBe("?actor=alice");
  });

  it("says when nothing matches", async () => {
    serve(0);
    renderPage();
    expect(await screen.findByText("No API tokens")).toBeInTheDocument();
  });
});

describe("every account's API tokens in Polish", () => {
  beforeEach(() => {
    localStorage.clear();
    setPreferences({ language: "pl" });
  });
  afterEach(() => {
    resetPreferences();
    vi.unstubAllGlobals();
  });

  it("names the columns, filters, counts and actions in Polish", async () => {
    serve(22);
    renderPage();
    expect(await screen.findByText("22 tokeny")).toBeInTheDocument();
    expect(document.title).toBe("Wszystkie tokeny API - ExactDocs");
    const table = screen.getByRole("table", { name: "Tokeny API wszystkich kont" });
    for (const header of ["Nazwa", "Właściciel", "Biblioteki", "Wygasa", "Ostatnie użycie"]) {
      expect(
        within(table).getByRole("columnheader", { name: new RegExp(header) }),
      ).toBeInTheDocument();
    }
    expect(within(await rowOf("token 01")).getByText("Wygasł")).toBeInTheDocument();
    const views = screen.getByRole("navigation", { name: "Widoki użytkowników" });
    expect(within(views).getByRole("link", { name: "Tokeny API" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ważność" }));
    expect(await screen.findByRole("option", { name: "Wygasłe" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Więcej opcji: token 02 (bob)" }));
    expect(
      await screen.findByRole("menuitem", { name: "Pokaż tokeny tej osoby" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Pokaż wpisy tej osoby w dzienniku dostępu" }),
    ).toBeInTheDocument();
  });
});
