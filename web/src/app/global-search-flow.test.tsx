import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAppRouter } from "./router";

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
const facets = [
  { library: "/acme/payments", version: "v2.0.0", commit_sha: SHA, matches: 3 },
  { library: "/fixture/docs-repo", version: "v2.0.0", commit_sha: SHA, matches: 1 },
];

function mount(path: string) {
  const calls: URL[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = new URL(input, "http://x");
      calls.push(url);
      if (url.pathname.endsWith("/session")) {
        return Response.json({
          state: "signed_in",
          account: { id: "1", username: "ada", role: "admin" },
        });
      }
      if (url.pathname.endsWith("/v1/search")) {
        const only = url.searchParams.get("library");
        const results = [hit("/acme/payments", 1), hit("/fixture/docs-repo", 2)].filter(
          (h) => !only || h.library === only,
        );
        return Response.json({
          notice: "",
          retrieval_mode: "bm25",
          reranked: false,
          coverage: { candidates: results.length, reranked: 0, complete: true },
          libraries_searched: 2,
          libraries_omitted: 0,
          libraries: facets,
          results,
        });
      }
      return Response.json({ error: "not_found", detail: "x", fields: [] }, { status: 404 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: [path] }));
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, searches: () => calls.filter((u) => u.pathname.endsWith("/v1/search")) };
}

describe("searching all libraries", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("opens /search from the header box and keeps the query in the URL", async () => {
    const { router, searches } = mount("/account");
    const box = await screen.findByRole("searchbox", { name: "Search all libraries" });
    await userEvent.type(box, "token{Enter}");
    expect(await screen.findAllByRole("link", { name: /Tokens/ })).toHaveLength(2);
    expect(router.state.location.search).toMatchObject({ q: "token" });
    expect(searches()[0]?.searchParams.get("q")).toBe("token");
    expect(searches()[0]?.searchParams.has("library")).toBe(false);
  });

  it("narrows to one library while the counts stay", async () => {
    const { router, searches } = mount("/search?q=token");
    const facet = await screen.findByRole("link", { name: /\/fixture\/docs-repo\s*1/ });
    expect(screen.getByRole("link", { name: /All libraries\s*4/ })).toBeVisible();
    await userEvent.click(facet);
    await waitFor(() =>
      expect(searches().at(-1)?.searchParams.get("library")).toBe("/fixture/docs-repo"),
    );
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Tokens/ })).toHaveLength(1));
    expect(router.state.location.search).toMatchObject({ library: "/fixture/docs-repo" });
    const nav = screen.getByRole("navigation", { name: "Libraries with matches" });
    expect(within(nav).getByRole("link", { name: /\/acme\/payments\s*3/ })).toBeVisible();
  });

  it("links a result to its library and version at the anchor", async () => {
    const { router } = mount("/search?q=token");
    await userEvent.click(
      (await screen.findAllByRole("link", { name: /Tokens/ }))[0] as HTMLElement,
    );
    expect(router.state.location.pathname).toBe("/libraries/acme/payments");
    expect(router.state.location.search).toMatchObject({ version: "v2.0.0", path: "docs/auth.md" });
    expect(router.state.location.hash).toBe("refresh");
  });
});
