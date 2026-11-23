import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { GlobalSearchPage, SearchBox, SearchResults } from "./index";
import type { SearchContext } from "./model/context";

const SHA = "2af418f7206a048fd5c2c0b4f06330b0dd48b0ff";

const hit = (library: string, n: number) => ({
  chunk_id: `${library}-${n}`,
  article_path: "docs/auth.md",
  heading_path: ["Tokens", "Refresh"],
  anchor: "refresh",
  position: n,
  total: 3,
  prev_chunk_id: null,
  next_chunk_id: null,
  commit_sha: SHA,
  source_url: null,
  tags: [],
  score: 1,
  snippet: "Rotate the token before it expires.",
  highlights: [{ start: 11, end: 16 }],
  library,
  version: "v2.0.0",
});

function serve() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = new URL(input, "http://x");
      if (url.pathname.endsWith("/v1/search")) {
        return Response.json({
          notice: "",
          retrieval_mode: "bm25",
          reranked: false,
          coverage: { candidates: 2, reranked: 0, complete: false },
          libraries_searched: 2,
          libraries_omitted: 3,
          libraries: [
            { library: "/acme/payments", version: "v2.0.0", commit_sha: SHA, matches: 3 },
            { library: "/fixture/docs-repo", version: "v2.0.0", commit_sha: SHA, matches: 1 },
          ],
          results: [hit("/acme/payments", 1), hit("/fixture/docs-repo", 2)],
        });
      }
      if (url.pathname.endsWith("/libraries/acme/payments/search")) {
        return Response.json({
          notice: "",
          library: "/acme/payments",
          version: "v1",
          commit_sha: SHA,
          retrieval_mode: "lexical",
          reranked: false,
          coverage: { candidates: 0, reranked: 0, complete: true },
          fallback_reason: null,
          results: [],
        });
      }
      if (url.pathname.endsWith("/tags")) {
        return Response.json({ tags: [{ tag: "auth", count: 2 }], truncated: false });
      }
      return Response.json({ error: "not_found", detail: "x", fields: [] }, { status: 404 });
    }),
  );
}

function renderAt(start: string, page: () => React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TestRouter
        pages={{ "/search": page, "/libraries/$owner/$repo": page, "/": () => <p>Home</p> }}
        start={start}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => setPreferences({ language: "pl" }));
afterEach(() => {
  resetPreferences();
  vi.unstubAllGlobals();
});

describe("search in Polish", () => {
  it("words the global results, the facets and the counts in Polish", async () => {
    serve();
    renderAt("/search?q=token", () => <GlobalSearchPage q="token" />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Wyszukiwanie: token" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Przeszukuje domyślną wersję każdej biblioteki.")).toBeInTheDocument();
    expect(
      screen.getAllByRole("searchbox", { name: "Szukaj we wszystkich bibliotekach" }).length,
    ).toBeGreaterThan(0);

    expect(
      await screen.findByRole("link", { name: "Wszystkie biblioteki, 4 trafienia" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "/acme/payments, 3 trafienia" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "/fixture/docs-repo, 1 trafienie" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2 najlepsze z 4")).toBeInTheDocument();
    expect(screen.getByText(/w 2 bibliotekach/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Pokazano 2 najlepsze wyniki. Pasuje więcej fragmentów: wybierz bibliotekę powyżej lub użyj bardziej szczegółowego słowa.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Przeszukano 2 z 5 bibliotek; pozostałych 3 tutaj się nie przeszukuje\./),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Przejrzyj je na stronie Biblioteki" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "2 najlepsze wyniki dla „token” we wszystkich bibliotekach",
    );
  });

  it("says in Polish that a version has nothing, and offers to widen", async () => {
    serve();
    const ctx: SearchContext = {
      owner: "acme",
      repo: "payments",
      ref: "v1",
      sha: SHA,
      q: "retry",
      tags: "auth,billing",
      match: "any",
      otherRefs: ["v2"],
    };
    renderAt("/libraries/acme/payments?q=retry", () => (
      <>
        <SearchBox ctx={ctx} />
        <SearchResults ctx={ctx} />
      </>
    ));

    expect(
      await screen.findByRole("heading", { level: 2, name: "Brak wyników w v1" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/nic nie pasuje do/).closest("p") as HTMLElement).toHaveTextContent(
      "W v1 nic nie pasuje do „retry” wśród artykułów z tagiem auth lub billing. Wpisz mniej słów lub inne.",
    );
    expect(screen.getByRole("button", { name: "Usuń filtr tagów" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Zamiast tego szukaj w\sv2$/ })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Szukaj w v1" })).toBeInTheDocument();
    // An icon-only control: its tooltip repeats its name.
    const clear = screen.getByRole("button", { name: "Wyczyść wyszukiwanie" });
    act(() => clear.focus());
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Wyczyść wyszukiwanie");
    expect(screen.getByRole("button", { name: "Dowolny tag" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Brak wyników dla „retry” w v1");
  });
});
