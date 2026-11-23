import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { LibrariesPage } from "./index";
import { listFilters, listParams, parseListView } from "./model/list-view";

const library = (n: number) => ({
  id: `/acme/lib${n}`,
  title: `Library ${n}`,
  description: `What library ${n} is`,
  default_version: "v1.0.0",
  default_pinned: false,
  source_url: `https://github.com/acme/lib${n}.git`,
  version_count: 1,
  refs: [],
  tags: [],
  last_imported_at: "2026-11-01T10:00:00Z",
});

/** `count` libraries behind an API that honours `limit` and an offset cursor (`o<n>`). */
function serve(count = 25) {
  const all = Array.from({ length: count }, (_, i) => library(i + 1));
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(String(input), "http://x");
    if (url.pathname.endsWith("/v1/libraries")) {
      const rows = url.searchParams.get("q") === "nothing" ? [] : all;
      const start = Number(url.searchParams.get("cursor")?.slice(1) ?? 0);
      const limit = Number(url.searchParams.get("limit"));
      return Response.json({
        libraries: rows.slice(start, start + limit),
        next_cursor: start + limit < rows.length ? `o${start + limit}` : null,
        total: rows.length,
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
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <TestRouter history={history} pages={{ "/": LibrariesPage }} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

describe("the libraries list view", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("keeps only what the API knows from a hand-edited URL", () => {
    expect(
      parseListView({
        q: " azure ",
        sort: "-title",
        ai: "off",
        versions: "none",
        imported: "7d",
        page: "2",
        size: "50",
        x: 1,
      }),
    ).toEqual({
      q: "azure",
      sort: "-title",
      ai: "off",
      versions: "none",
      imported: "7d",
      page: 2,
      size: 50,
    });
    expect(
      parseListView({ sort: "password", ai: "maybe", versions: "all", imported: "1y", q: "" }),
    ).toEqual({});
    const now = Date.parse("2026-11-23T12:00:30Z");
    expect(
      listParams(listFilters({ q: "a b", sort: "-last_imported_at", ai: "off" }, now), 20, "c1"),
    ).toBe("limit=20&q=a+b&sort=-last_imported_at&ai_enabled=false&cursor=c1");
    expect(listParams(listFilters({ versions: "some", imported: "24h" }, now), 5)).toBe(
      "limit=5&has_versions=true&updated_after=2026-11-22T12%3A00%3A00.000Z",
    );
    expect(listParams(listFilters({ imported: "older" }, now), 5)).toBe(
      "limit=5&updated_before=2026-10-24T12%3A00%3A00.000Z",
    );
  });

  it("pages with numbered pages, the next one fetched ahead", async () => {
    const fetchMock = serve();
    const history = renderPage();

    expect(await screen.findByText("1–20 of 25")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Libraries" })).toHaveAttribute("aria-rowcount", "26");
    await waitFor(() => expect(urls(fetchMock)).toContain("/api/v1/libraries?limit=20&cursor=o20"));

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByText("21–25 of 25")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Library 21" })).toBeInTheDocument();
    expect(history.location.search).toContain("page=2");
  });

  it("reads the view from the URL and sends it to the API", async () => {
    const fetchMock = serve();
    renderPage("/?q=azure&sort=-version_count&ai=on&size=5");

    await screen.findByText("Library 1");
    expect(urls(fetchMock)[0]).toBe(
      "/api/v1/libraries?limit=5&q=azure&sort=-version_count&ai_enabled=true",
    );
    expect(screen.getByRole("searchbox")).toHaveValue("azure");
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(within(chips).getByText("AI on")).toBeInTheDocument();
  });

  it("sorts on the server and keeps the sort in the URL", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("Library 1");

    await userEvent.click(screen.getByRole("button", { name: "Sort by Last imported" }));

    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/libraries?limit=20&sort=-last_imported_at"),
    );
    expect(history.location.search).toContain("sort=-last_imported_at");
    expect(screen.getByRole("columnheader", { name: /Last imported/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("filters with a facet on the server", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("Library 1");

    await userEvent.click(screen.getByRole("button", { name: "Versions" }));
    await userEvent.click(await screen.findByRole("option", { name: "Without versions" }));
    await userEvent.keyboard("{Escape}");

    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/libraries?limit=20&has_versions=false"),
    );
    expect(history.location.search).toContain("versions=none");
  });

  it("filters on the server and says when nothing matches", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("Library 1");

    await userEvent.type(screen.getByRole("searchbox"), "nothing");

    expect(await screen.findByText("No libraries match")).toBeInTheDocument();
    expect(urls(fetchMock).at(-1)).toBe("/api/v1/libraries?limit=20&q=nothing");
    expect(history.location.search).toContain("q=nothing");

    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("Library 1")).toBeInTheDocument();
    expect(screen.getByRole("searchbox")).toHaveValue("");
  });
});
