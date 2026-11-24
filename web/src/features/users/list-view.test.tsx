import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { UsersPage } from "./index";
import { parseUsersView, usersFilters, usersParams } from "./model/list-view";

const user = (n: number) => ({
  id: `u${n}`,
  username: `user${String(n).padStart(2, "0")}`,
  role: n % 4 === 0 ? "admin" : "user",
  created_at: "2026-11-13T10:00:00Z",
  disabled: n % 5 === 0,
  // Every third account signs in through GitHub; the first was active an hour ago, the second never.
  provider: n % 3 === 0 ? "github" : null,
  groups: [],
  last_active_at: n === 1 ? new Date(Date.now() - 3_600_000).toISOString() : null,
  token_count: n === 1 ? 3 : 0,
});

/**
 * A users API over `count` accounts that honours `limit` and an `offset` (or a cursor, `o<n>`);
 * `q=nobody` matches nothing.
 */
function serve(count = 45) {
  const all = Array.from({ length: count }, (_, i) => user(i + 1));
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(String(input), "http://x");
    const providers = url.searchParams.getAll("provider");
    const rows =
      url.searchParams.get("q") === "nobody"
        ? []
        : all.filter((u) => !providers.length || providers.includes(u.provider ?? "password"));
    const start = Number(
      url.searchParams.get("offset") ?? url.searchParams.get("cursor")?.slice(1) ?? 0,
    );
    const limit = Number(url.searchParams.get("limit"));
    return Response.json({
      users: rows.slice(start, start + limit),
      next_cursor: start + limit < rows.length ? `o${start + limit}` : null,
      total: rows.length,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const urls = (fetchMock: ReturnType<typeof serve>) =>
  fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/v1/users?"));

function renderPage(start = "/users") {
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
            "/users": () => (
              <UsersPage
                currentUserId="u1"
                providers={[
                  { name: "github", display_name: "GitHub" },
                  { name: "corp", display_name: "Corp SSO" },
                ]}
              />
            ),
            "/access-log": () => <p>Access log</p>,
            "/users/tokens": () => <p>All tokens</p>,
          }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

describe("the users table", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("keeps only what the API knows from a hand-edited URL", () => {
    expect(
      parseUsersView({
        q: " bo ",
        sort: "-username",
        role: "admin",
        status: "disabled",
        page: 2,
        size: 50,
      }),
    ).toEqual({
      q: "bo",
      sort: "-username",
      role: ["admin"],
      status: ["disabled"],
      page: 2,
      size: 50,
    });
    expect(parseUsersView({ sort: "password", role: "root", status: "gone", size: 7 })).toEqual({
      q: undefined,
      sort: undefined,
      page: undefined,
      size: undefined,
      role: undefined,
      status: undefined,
      provider: undefined,
    });
    // Sign-in methods: `password` or provider names as the server allows them, each once.
    expect(parseUsersView({ provider: "password,github,Bad Name,github,-x" }).provider).toEqual([
      "password",
      "github",
    ]);
    expect(usersParams(usersFilters({ provider: ["password", "github"] }), 20)).toBe(
      "limit=20&provider=password&provider=github",
    );
    expect(parseUsersView({ sort: "-last_active_at" }).sort).toBe("-last_active_at");
    expect(parseUsersView({ sort: "token_count" }).sort).toBe("token_count");
    expect(
      usersParams(
        usersFilters({ q: "b", sort: "role", role: ["user"], status: ["active"] }),
        20,
        "c1",
      ),
    ).toBe("limit=20&q=b&role=user&disabled=false&sort=role&cursor=c1");
    expect(usersParams({ sort: "role" }, 20, null, 60)).toBe("limit=20&sort=role&offset=60");
    // Every role, or both states, is no filter at all.
    expect(usersFilters({ role: ["admin", "user"], status: ["active", "disabled"] })).toEqual({});
  });

  it("pages with numbered pages and shows the server's total", async () => {
    const fetchMock = serve();
    const history = renderPage();

    expect(await screen.findByText("1–20 of 45")).toBeInTheDocument();
    expect(screen.getByText("45 accounts")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "User accounts" });
    expect(table).toHaveAttribute("aria-rowcount", "46");
    expect(urls(fetchMock)[0]).toBe("/api/v1/users?limit=20&offset=0");

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByText("21–40 of 45")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("user21")).toBeInTheDocument();
    expect(history.location.search).toContain("page=2");
    expect(urls(fetchMock)).toContain("/api/v1/users?limit=20&offset=20");

    await userEvent.click(screen.getByRole("button", { name: "Last page" }));

    expect(await screen.findByText("41–45 of 45")).toBeInTheDocument();
    expect(urls(fetchMock)).toContain("/api/v1/users?limit=20&offset=40");
    expect(urls(fetchMock).every((u) => !u.includes("cursor="))).toBe(true);
  });

  it("opens a linked page with one request", async () => {
    const fetchMock = serve();
    renderPage("/users?page=2&size=5");
    expect(await screen.findByText("6–10 of 45")).toBeInTheDocument();
    expect(urls(fetchMock)[0]).toBe("/api/v1/users?limit=5&offset=5");
    await userEvent.click(screen.getByRole("button", { name: "Page 4" }));
    expect(await screen.findByText("16–20 of 45")).toBeInTheDocument();
    expect(urls(fetchMock)).toContain("/api/v1/users?limit=5&offset=15");
  });

  it("asks the server to sort when a column header is pressed", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 45");
    // The API's own order, oldest first, shows on the Created column.
    expect(screen.getByRole("columnheader", { name: /Created/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );

    await userEvent.click(screen.getByRole("button", { name: "Sort by Account" }));

    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/users?limit=20&sort=username&offset=0"),
    );
    expect(history.location.search).toContain("sort=username");
    expect(screen.getByRole("columnheader", { name: /Account/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
  });

  it("filters by role and state on the server, with chips", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 45");

    await userEvent.click(screen.getByRole("button", { name: "Role" }));
    await userEvent.click(await screen.findByRole("option", { name: "Admin" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Status" }));
    await userEvent.click(await screen.findByRole("option", { name: "Disabled" }));
    await userEvent.keyboard("{Escape}");

    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/users?limit=20&role=admin&disabled=true&offset=0"),
    );
    expect(history.location.search).toContain("role=admin");
    expect(history.location.search).toContain("status=disabled");
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(
      within(chips)
        .getAllByRole("listitem")
        .map((c) => c.textContent),
    ).toEqual(["Role: Admin", "Status: Disabled"]);
  });

  it("shows when each account was last active and how many tokens it holds", async () => {
    serve();
    renderPage();
    const table = await screen.findByRole("table", { name: "User accounts" });
    await within(table).findByText("user01");
    const rowOf = (name: string) => within(table).getByText(name).closest("tr") as HTMLElement;
    expect(within(table).getByRole("columnheader", { name: /Last active/ })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: /Tokens/ })).toBeInTheDocument();
    expect(within(rowOf("user01")).getByText("1 hour ago")).toBeInTheDocument();
    expect(within(rowOf("user01")).getByText("3")).toBeInTheDocument();
    expect(within(rowOf("user02")).getByText("Never")).toBeInTheDocument();
    // A configured provider by the name people know it by.
    expect(within(rowOf("user03")).getByText("GitHub")).toBeInTheDocument();
  });

  it("sorts by last activity and by tokens on the server, newest and most first", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 45");

    await userEvent.click(screen.getByRole("button", { name: "Sort by Last active" }));
    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/users?limit=20&sort=-last_active_at&offset=0"),
    );
    expect(history.location.search).toContain("sort=-last_active_at");

    await userEvent.click(screen.getByRole("button", { name: "Sort by Tokens" }));
    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/users?limit=20&sort=-token_count&offset=0"),
    );
  });

  it("filters by where accounts sign in: a password or a configured provider", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 45");

    await userEvent.click(screen.getByRole("button", { name: "Sign-in" }));
    const options = within(await screen.findByRole("listbox")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Password", "GitHub", "Corp SSO"]);
    await userEvent.click(screen.getByRole("option", { name: "GitHub" }));
    await userEvent.click(screen.getByRole("option", { name: "Password" }));
    await userEvent.keyboard("{Escape}");

    await waitFor(() =>
      expect(urls(fetchMock)).toContain(
        "/api/v1/users?limit=20&provider=password&provider=github&offset=0",
      ),
    );
    expect(history.location.search).toContain("provider=password%2Cgithub");
    expect(await screen.findByText("1–20 of 45")).toBeInTheDocument();
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(
      within(chips)
        .getAllByRole("listitem")
        .map((c) => c.textContent),
    ).toEqual(["Sign-in: Password", "Sign-in: GitHub"]);
  });

  it("keeps a provider from a link that is no longer configured", async () => {
    const fetchMock = serve();
    renderPage("/users?provider=okta");
    expect(await screen.findByText("No accounts match")).toBeInTheDocument();
    expect(urls(fetchMock)[0]).toBe("/api/v1/users?limit=20&provider=okta&offset=0");
    await userEvent.click(screen.getByRole("button", { name: "Sign-in, 1 selected" }));
    expect(await screen.findByRole("option", { name: "okta" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("leads from an account to its access-log entries and to its tokens", async () => {
    serve();
    const history = renderPage();
    await screen.findByText("1–20 of 45");

    await userEvent.click(screen.getByRole("button", { name: "More actions for user02" }));
    await userEvent.click(
      await screen.findByRole("menuitem", { name: "Show their access-log entries" }),
    );
    expect(await screen.findByText("Access log")).toBeInTheDocument();
    expect(history.location.pathname).toBe("/access-log");
    expect(history.location.search).toBe("?actor=user02");

    history.back();
    await userEvent.click(await screen.findByRole("button", { name: "More actions for user02" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Show their API tokens" }));
    expect(await screen.findByText("All tokens")).toBeInTheDocument();
    expect(history.location.pathname).toBe("/users/tokens");
    expect(history.location.search).toBe("?owner=u2");
  });

  it("links to every account's tokens beside the accounts", async () => {
    serve();
    renderPage();
    const views = await screen.findByRole("navigation", { name: "Users views" });
    expect(within(views).getByRole("link", { name: "Accounts" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(views).getByRole("link", { name: "API tokens" })).toHaveAttribute(
      "href",
      "/users/tokens",
    );
  });

  it("says when nothing matches and clears the filters", async () => {
    const fetchMock = serve();
    const history = renderPage("/users?q=nobody&status=disabled");

    expect(await screen.findByText("No accounts match")).toBeInTheDocument();
    expect(urls(fetchMock)[0]).toBe("/api/v1/users?limit=20&q=nobody&disabled=true&offset=0");
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(await screen.findByText("1–20 of 45")).toBeInTheDocument();
    expect(history.location.search).toBe("");
  });
});
