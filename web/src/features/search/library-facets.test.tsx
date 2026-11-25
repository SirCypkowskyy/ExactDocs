import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useSearch } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { GlobalSearchPage } from "./index";

const SHA = "2af418f7206a048fd5c2c0b4f06330b0dd48b0ff";

/** Ten libraries with matches, the most first: eight chips, the last two behind "+2 more". */
const FACETS = Array.from({ length: 10 }, (_, i) => ({
  library: `/org/lib-${i}`,
  version: "v1",
  commit_sha: SHA,
  matches: 20 - i,
}));

function serve() {
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(input, "http://x");
    const only = url.searchParams.get("library");
    return Response.json({
      notice: "",
      retrieval_mode: "bm25",
      reranked: false,
      coverage: { candidates: 1, reranked: 0, complete: true },
      libraries_searched: 10,
      libraries_omitted: 0,
      libraries: FACETS,
      results: [
        {
          chunk_id: "c1",
          article_path: "docs/a.md",
          heading_path: ["A"],
          anchor: "a",
          position: 0,
          total: 1,
          prev_chunk_id: null,
          next_chunk_id: null,
          commit_sha: SHA,
          source_url: null,
          tags: [],
          score: 1,
          snippet: "token",
          highlights: [],
          library: only ?? "/org/lib-0",
          version: "v1",
        },
      ],
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function Page() {
  const { library } = useSearch({ strict: false }) as { library?: string };
  return <GlobalSearchPage q="token" {...(library && { library })} />;
}

function renderAt(start: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TestRouter pages={{ "/search": Page }} start={start} />
    </QueryClientProvider>,
  );
}

const searched = (fetchMock: ReturnType<typeof serve>) =>
  fetchMock.mock.calls.map(([u]) => new URL(String(u), "http://x").searchParams.get("library"));

beforeEach(() => localStorage.removeItem("exactdocs-recent-libraries"));
afterEach(() => {
  resetPreferences();
  vi.unstubAllGlobals();
});

describe("the global search's library facets", () => {
  it("keeps the rest of the libraries in the library combobox, with their counts", async () => {
    const fetchMock = serve();
    renderAt("/search?q=token");
    const facets = await screen.findByRole("navigation", { name: "Libraries with matches" });
    expect(within(facets).getAllByRole("link")).toHaveLength(9); // All, then eight libraries
    await userEvent.click(within(facets).getByRole("button", { name: "+2 more libraries" }));
    const list = screen.getByRole("listbox", { name: "Libraries with matches" });
    expect(
      within(list)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["/org/lib-812, 12 matches", "/org/lib-911, 11 matches"]);
    expect(within(list).getByRole("option", { name: "/org/lib-9, 11 matches" })).toBeVisible();
    await userEvent.keyboard("lib-9{Enter}");
    // Picking one narrows the search to it, as its chip would.
    await waitFor(() => expect(searched(fetchMock)).toContain("/org/lib-9"));
    expect(await screen.findByRole("link", { name: "/org/lib-9, 11 matches" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("speaks Polish", async () => {
    setPreferences({ language: "pl" });
    serve();
    renderAt("/search?q=token");
    await userEvent.click(await screen.findByRole("button", { name: "+2 kolejne biblioteki" }));
    expect(screen.getByRole("listbox", { name: "Biblioteki z trafieniami" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "/org/lib-8, 12 trafień" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Znajdź bibliotekę" })).toHaveFocus();
  });
});
