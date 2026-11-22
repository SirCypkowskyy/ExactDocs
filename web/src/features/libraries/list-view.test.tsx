import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { LibrariesPage } from "./index";
import { listParams, parseListView } from "./model/list-view";

const library = (n: number) => ({
  id: `/acme/lib${n}`,
  title: `Library ${n}`,
  description: "",
  default_version: "v1.0.0",
  default_pinned: false,
  source_url: `https://github.com/acme/lib${n}.git`,
  version_count: 1,
  refs: [],
  tags: [],
  last_imported_at: "2026-11-01T10:00:00Z",
});

/** Two pages of libraries (cursor "p2" is the second); `total` is what the filters match. */
function serve(total = 3) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.includes("/v1/libraries?")) {
      const second = url.includes("cursor=p2");
      const empty = url.includes("q=nothing");
      return Response.json({
        libraries: empty ? [] : second ? [library(3)] : [library(1), library(2)],
        next_cursor: second || empty ? null : "p2",
        total: empty ? 0 : total,
      });
    }
    return Response.json({ jobs: [] });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const urls = (fetchMock: ReturnType<typeof serve>) =>
  fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/v1/libraries?"));

function renderPage(start = "/") {
  const history = createMemoryHistory({ initialEntries: [start] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TestRouter history={history} pages={{ "/": LibrariesPage }} />
    </QueryClientProvider>,
  );
  return history;
}

describe("the libraries list view", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps only what the API knows from a hand-edited URL", () => {
    expect(parseListView({ q: " azure ", sort: "-title", ai: "off", x: 1 })).toEqual({
      q: "azure",
      sort: "-title",
      ai: "off",
    });
    expect(parseListView({ sort: "password", ai: "maybe", q: "" })).toEqual({
      q: undefined,
      sort: undefined,
      ai: undefined,
    });
    expect(listParams({ q: "a b", sort: "-last_imported_at", ai: "off" }, "c1")).toBe(
      "limit=50&q=a+b&sort=-last_imported_at&ai_enabled=false&cursor=c1",
    );
  });

  it("shows the first page, prefetches the next, and shows it on demand", async () => {
    const fetchMock = serve();
    renderPage();

    expect(await screen.findByText("Showing 2 of 3")).toBeInTheDocument();
    // The next page is fetched ahead, but only shown when asked for.
    await waitFor(() =>
      expect(urls(fetchMock)).toEqual([
        "/api/v1/libraries?limit=50",
        "/api/v1/libraries?limit=50&cursor=p2",
      ]),
    );
    expect(screen.queryByText("Library 3")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(screen.getByText("Library 3")).toBeInTheDocument();
    expect(screen.getByText("Showing 3 of 3")).toBeInTheDocument();
    expect(urls(fetchMock)).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("reads the view from the URL and sends it to the API", async () => {
    const fetchMock = serve();
    renderPage("/?q=azure&sort=-version_count&ai=on");

    await screen.findByText("Library 1");
    expect(urls(fetchMock)[0]).toBe(
      "/api/v1/libraries?limit=50&q=azure&sort=-version_count&ai_enabled=true",
    );
    expect(screen.getByRole("searchbox")).toHaveValue("azure");
  });

  it("sorts on the server and keeps the sort in the URL", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("Library 1");

    await userEvent.click(screen.getByRole("button", { name: "Sort by Last imported" }));

    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/libraries?limit=50&sort=-last_imported_at"),
    );
    expect(history.location.search).toContain("sort=-last_imported_at");
    expect(
      screen.getByRole("button", { name: "Sort by Last imported, sorted descending" }),
    ).toBeInTheDocument();
  });

  it("filters on the server and says when nothing matches", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("Library 1");

    await userEvent.type(screen.getByRole("searchbox"), "nothing");

    expect(await screen.findByText("No libraries match")).toBeInTheDocument();
    expect(urls(fetchMock).at(-1)).toBe("/api/v1/libraries?limit=50&q=nothing");
    expect(history.location.search).toContain("q=nothing");

    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("Library 1")).toBeInTheDocument();
    expect(screen.getByRole("searchbox")).toHaveValue("");
  });
});
