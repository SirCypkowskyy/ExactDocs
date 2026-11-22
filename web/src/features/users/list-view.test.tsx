import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UsersPage } from "./index";
import { parseUsersView, type UsersView, usersParams } from "./model/list-view";

const user = (n: number) => ({
  id: `u${n}`,
  username: `user${n}`,
  role: "user",
  created_at: "2026-11-13T10:00:00Z",
  disabled: false,
  provider: null,
  groups: [],
});

/** Two pages of accounts (cursor "p2" is the second); `q=nobody` matches nothing. */
function serve() {
  const fetchMock = vi.fn(async (url: string) => {
    const second = url.includes("cursor=p2");
    const empty = url.includes("q=nobody");
    return Response.json({
      users: empty ? [] : second ? [user(3)] : [user(1), user(2)],
      next_cursor: second || empty ? null : "p2",
      total: empty ? 0 : 3,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const urls = (fetchMock: ReturnType<typeof serve>) => fetchMock.mock.calls.map(([u]) => String(u));

/** The route keeps the view in the URL; here a state stands in for it. */
function Harness({ start, seen }: { start: UsersView; seen: UsersView[] }) {
  const [view, setView] = useState(start);
  return (
    <UsersPage
      currentUserId="u1"
      view={view}
      onView={(next) => {
        seen.push(next);
        setView(next);
      }}
    />
  );
}

function renderPage(start: UsersView = {}) {
  const seen: UsersView[] = [];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness start={start} seen={seen} />
    </QueryClientProvider>,
  );
  return seen;
}

describe("the users list view", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps only what the API knows from a hand-edited URL", () => {
    expect(
      parseUsersView({ q: " bo ", sort: "-username", role: "admin", status: "disabled" }),
    ).toEqual({ q: "bo", sort: "-username", role: "admin", status: "disabled" });
    expect(parseUsersView({ sort: "password", role: "root", status: "gone" })).toEqual({
      q: undefined,
      sort: undefined,
      role: undefined,
      status: undefined,
    });
    expect(usersParams({ q: "b", sort: "role", role: "user", status: "active" }, "c1")).toBe(
      "limit=50&q=b&sort=role&role=user&disabled=false&cursor=c1",
    );
  });

  it("loads the next page on demand and shows the server's total", async () => {
    const fetchMock = serve();
    renderPage();

    expect(await screen.findByText("Showing 2 of 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Showing 3 of 3")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(urls(fetchMock)).toEqual(["/api/v1/users?limit=50", "/api/v1/users?limit=50&cursor=p2"]);
  });

  it("asks the server to sort when a column header is clicked", async () => {
    const fetchMock = serve();
    const seen = renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Sort by Account" }));

    expect(seen.at(-1)).toEqual({ sort: "username" });
    await waitFor(() => expect(urls(fetchMock)).toContain("/api/v1/users?limit=50&sort=username"));
    expect(
      screen.getByRole("button", { name: "Sort by Account, sorted ascending" }),
    ).toBeInTheDocument();
  });

  it("filters on the server and offers to clear filters when nothing matches", async () => {
    const fetchMock = serve();
    const seen = renderPage({ q: "nobody", status: "disabled" });

    expect(await screen.findByText("No accounts match")).toBeInTheDocument();
    expect(urls(fetchMock)).toEqual(["/api/v1/users?limit=50&q=nobody&disabled=true"]);
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(seen.at(-1)).toEqual({ sort: undefined });
  });
});
