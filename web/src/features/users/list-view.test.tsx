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
  provider: null,
  groups: [],
});

/**
 * A users API over `count` accounts that honours `limit` and an offset cursor (`o<n>`); `q=nobody`
 * matches nothing.
 */
function serve(count = 45) {
  const all = Array.from({ length: count }, (_, i) => user(i + 1));
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(String(input), "http://x");
    const rows = url.searchParams.get("q") === "nobody" ? [] : all;
    const start = Number(url.searchParams.get("cursor")?.slice(1) ?? 0);
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
          pages={{ "/users": () => <UsersPage currentUserId="u1" /> }}
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
    });
    expect(
      usersParams(
        usersFilters({ q: "b", sort: "role", role: ["user"], status: ["active"] }),
        20,
        "c1",
      ),
    ).toBe("limit=20&q=b&role=user&disabled=false&sort=role&cursor=c1");
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
    expect(urls(fetchMock)[0]).toBe("/api/v1/users?limit=20");

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByText("21–40 of 45")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("user21")).toBeInTheDocument();
    expect(history.location.search).toContain("page=2");
    expect(urls(fetchMock)).toContain("/api/v1/users?limit=20&cursor=o20");
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

    await waitFor(() => expect(urls(fetchMock)).toContain("/api/v1/users?limit=20&sort=username"));
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
      expect(urls(fetchMock)).toContain("/api/v1/users?limit=20&role=admin&disabled=true"),
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

  it("says when nothing matches and clears the filters", async () => {
    const fetchMock = serve();
    const history = renderPage("/users?q=nobody&status=disabled");

    expect(await screen.findByText("No accounts match")).toBeInTheDocument();
    expect(urls(fetchMock)[0]).toBe("/api/v1/users?limit=20&q=nobody&disabled=true");
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(await screen.findByText("1–20 of 45")).toBeInTheDocument();
    expect(history.location.search).toBe("");
  });
});
