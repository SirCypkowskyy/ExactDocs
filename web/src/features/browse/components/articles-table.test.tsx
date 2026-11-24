import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, useSearch } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { articleFilters, articlesView } from "../model/articles-view";
import type { LibraryDetail, Version } from "../model/browse";
import { parseSearch } from "../model/search";
import { ArticlesTable } from "./articles-table";

const SHA = "2af418f7206a048fd5c2c0b4f06330b0dd48b0ff";
const version = {
  ref: "v1.4.0",
  kind: "tag",
  commit_sha: SHA,
  imported_at: "2026-11-01T10:00:00Z",
  is_default: true,
} as Version;
const library = {
  id: "/acme/payments",
  title: "Acme Payments",
  source_url: "https://github.com/acme/payments.git",
  host: "github",
  versions: [version],
  default_version: "v1.4.0",
} as unknown as LibraryDetail;

/** 26 articles: `docs/guide/a01.md`… in a folder, then `README.md` at the root. */
const ALL = [
  ...Array.from({ length: 25 }, (_, i) => ({
    path: `docs/guide/a${String(i + 1).padStart(2, "0")}.md`,
    title: `Article ${i + 1}`,
    tags: i === 0 ? ["api", "guide", "beta", "auth"] : i % 2 ? ["guide"] : [],
    size: 1000 * (i + 1),
  })),
  { path: "README.md", title: "Acme Payments", tags: [], size: 120 },
];

/** The articles API over ALL: `limit`, an `offset` (or a cursor, `o<n>`), `q`, `tags`, `path_prefix`. */
function serve() {
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(String(input), "http://x");
    if (url.pathname.endsWith("/tags")) {
      return Response.json({
        tags: [
          { tag: "guide", count: 12 },
          { tag: "api", count: 1 },
        ],
        truncated: false,
      });
    }
    const q = url.searchParams.get("q")?.toLowerCase();
    const tags = url.searchParams.get("tags")?.split(",") ?? [];
    const prefix = url.searchParams.get("path_prefix");
    const rows = ALL.filter(
      (a) =>
        (!q || a.path.includes(q) || a.title.toLowerCase().includes(q)) &&
        (tags.length === 0 || a.tags.some((t) => tags.includes(t))) &&
        (prefix === null || a.path.startsWith(`${prefix}/`)),
    );
    const start = Number(
      url.searchParams.get("offset") ?? url.searchParams.get("cursor")?.slice(1) ?? 0,
    );
    const limit = Number(url.searchParams.get("limit"));
    return Response.json({
      articles: rows.slice(start, start + limit),
      next_cursor: start + limit < rows.length ? `o${start + limit}` : null,
      total: rows.length,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** The table's requests, as the API saw them (the tag counts left out). */
const pages = (fetchMock: ReturnType<typeof serve>) =>
  fetchMock.mock.calls
    .map(([u]) => new URL(String(u), "http://x"))
    .filter((u) => u.pathname.endsWith("/articles"));

function Page() {
  const search = parseSearch(useSearch({ strict: false }) as Record<string, unknown>);
  return (
    <ArticlesTable
      owner="acme"
      repo="payments"
      library={library}
      version={version}
      search={search}
    />
  );
}

function renderTable(start = "/libraries/acme/payments") {
  const history = createMemoryHistory({ initialEntries: [start] });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TestRouter history={history} pages={{ "/libraries/$owner/$repo": Page }} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

const params = (history: ReturnType<typeof renderTable>) =>
  new URLSearchParams(history.location.search);

describe("the articles table", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    resetPreferences();
    vi.unstubAllGlobals();
  });

  it("reads its view from the library page's URL, leaving `q` to the search", () => {
    const search = parseSearch({
      q: "retry",
      filter: "auth",
      tags: "api,guide",
      prefix: "/docs/guide/",
      sort: "-size",
      page: "3",
      size: "50",
    });
    expect(search).toMatchObject({ q: "retry", filter: "auth", prefix: "docs/guide", page: 3 });
    expect(search.size).toBe(50);
    const view = articlesView(search);
    expect(view).toEqual({
      q: "auth",
      sort: "-size",
      page: 3,
      size: 50,
      tags: ["api", "guide"],
      prefix: "docs/guide",
    });
    expect(articleFilters(view)).toEqual({
      q: "auth",
      tags: ["api", "guide"],
      prefix: "docs/guide",
      sort: "-size",
    });
    expect(parseSearch({ sort: "password", page: "-1", size: "7" })).toMatchObject({
      sort: undefined,
      page: undefined,
      size: undefined,
    });
  });

  it("shows numbered pages of the version's articles with the folder muted", async () => {
    const fetchMock = serve();
    const history = renderTable();
    const table = await screen.findByRole("table", { name: "Articles" });
    const first = await within(table).findByRole("link", { name: "docs/guide/a01.md" });
    expect(first).toHaveAttribute("href", expect.stringContaining("path=docs%2Fguide%2Fa01.md"));
    expect(within(first).getByText("docs/guide/")).toHaveClass("text-muted-foreground");
    expect(screen.getByText("26 articles")).toBeInTheDocument();
    expect(screen.getByText("1–20 of 26")).toBeInTheDocument();
    // The table's requests never name a folder unless it is filtered to one.
    expect(pages(fetchMock)[0]?.searchParams.has("path_prefix")).toBe(false);
    expect(pages(fetchMock)[0]?.searchParams.get("limit")).toBe("20");
    expect(pages(fetchMock)[0]?.searchParams.get("offset")).toBe("0");
    // Tags: three, then "+1", which opens all of them.
    const row = first.closest("tr") as HTMLElement;
    expect(within(row).getByRole("list", { name: "Tags" })).toHaveTextContent("apiguidebeta+1");
    await userEvent.click(
      within(row).getByRole("button", { name: "1 more tag of docs/guide/a01.md" }),
    );
    expect(await screen.findByRole("dialog")).toHaveTextContent(
      "Tags of docs/guide/a01.mdapiguidebetaauth",
    );
    await userEvent.keyboard("{Escape}");
    expect(within(row).getByText("1 kB")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("21–26 of 26")).toBeInTheDocument();
    expect(params(history).get("page")).toBe("2");
    expect(screen.getByRole("link", { name: "README.md" })).toBeInTheDocument();
    expect(pages(fetchMock).some((u) => u.searchParams.get("offset") === "20")).toBe(true);
    expect(pages(fetchMock).some((u) => u.searchParams.has("cursor"))).toBe(false);
  });

  it("opens a deep page with one request by its offset, at the size in the URL", async () => {
    const fetchMock = serve();
    renderTable("/libraries/acme/payments?page=3&size=5");
    expect(await screen.findByText("11–15 of 26")).toBeInTheDocument();
    const [first] = pages(fetchMock);
    expect(first?.searchParams.get("limit")).toBe("5");
    expect(first?.searchParams.get("offset")).toBe("10");
    expect(first?.searchParams.has("cursor")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Last page" }));
    expect(await screen.findByText("26–26 of 26")).toBeInTheDocument();
    expect(pages(fetchMock).some((u) => u.searchParams.get("offset") === "25")).toBe(true);
    expect(screen.getByLabelText("Rows per page")).toHaveValue("5");
  });

  it("filters by text into `filter`, by tag and by folder, and clears all of it", async () => {
    const fetchMock = serve();
    const history = renderTable("/libraries/acme/payments?q=retry&page=2");
    await screen.findByText("21–26 of 26");

    await userEvent.type(screen.getByRole("searchbox", { name: "Find an article" }), "a2");
    await waitFor(() => expect(params(history).get("filter")).toBe("a2"));
    // The version's search keeps its own `q`; a new filter goes back to page 1.
    expect(params(history).get("q")).toBe("retry");
    expect(params(history).has("page")).toBe(false);
    await waitFor(() => expect(pages(fetchMock).at(-1)?.searchParams.get("q")).toBe("a2"));
    expect(await screen.findByText("1–6 of 6")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Tags" }));
    await userEvent.click(await screen.findByRole("option", { name: "guide" }));
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(params(history).get("tags")).toBe("guide"));
    await waitFor(() => expect(pages(fetchMock).at(-1)?.searchParams.get("tags")).toBe("guide"));

    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(within(chips).getByText("guide")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear all" }));
    await waitFor(() => expect(params(history).has("filter")).toBe(false));
    expect(params(history).has("tags")).toBe(false);
    expect(params(history).get("q")).toBe("retry");
    expect(screen.getByRole("searchbox", { name: "Find an article" })).toHaveValue("");
  });

  it("offers the same row actions in its menu and its context menu", async () => {
    const fetchMock = serve();
    const history = renderTable();
    const table = await screen.findByRole("table", { name: "Articles" });
    await within(table).findByRole("link", { name: "docs/guide/a01.md" });

    await userEvent.click(
      screen.getByRole("button", { name: "More actions for docs/guide/a01.md" }),
    );
    const menu = await screen.findByRole("menu");
    const names = within(menu)
      .getAllByRole("menuitem")
      .map((item) => item.textContent);
    expect(names).toEqual([
      "Open",
      "Copy path",
      "Copy link to this version",
      "Open on GitHub",
      "Show this folder's articles",
    ]);
    await userEvent.keyboard("{Escape}");

    // Shift+F10 on a focused row opens the same list where the focus is.
    within(table).getByRole("link", { name: "docs/guide/a01.md" }).focus();
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const context = await screen.findByRole("menu");
    expect(
      within(context)
        .getAllByRole("menuitem")
        .map((item) => item.textContent),
    ).toEqual(names);
    await userEvent.click(
      within(context).getByRole("menuitem", { name: "Show this folder's articles" }),
    );

    await waitFor(() => expect(params(history).get("prefix")).toBe("docs/guide"));
    await waitFor(() =>
      expect(pages(fetchMock).at(-1)?.searchParams.get("path_prefix")).toBe("docs/guide"),
    );
    expect(
      await screen.findByRole("button", { name: "Remove filter Folder: docs/guide" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("25 articles")).toBeInTheDocument();
  });

  it("says when nothing matches and when the list fails", async () => {
    serve();
    renderTable("/libraries/acme/payments?filter=nothing-like-this");
    expect(await screen.findByText("No articles match these filters.")).toBeInTheDocument();

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ error: "boom", detail: "boom" }, { status: 500 })),
    );
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load articles.");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("speaks Polish", async () => {
    setPreferences({ language: "pl" });
    serve();
    renderTable();
    expect(await screen.findByRole("table", { name: "Artykuły" })).toBeInTheDocument();
    expect(await screen.findByText("26 artykułów")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Znajdź artykuł" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Więcej opcji: docs/guide/a01.md" }));
    expect(
      await screen.findByRole("menuitem", { name: "Kopiuj link do tej wersji" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Otwórz w serwisie GitHub" })).toBeInTheDocument();
  });
});
