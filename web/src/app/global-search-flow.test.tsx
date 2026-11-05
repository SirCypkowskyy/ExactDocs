import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
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

const library = {
  id: "/acme/payments",
  title: "Acme Payments",
  description: "",
  source_url: "https://github.com/acme/payments.git",
  host: "github",
  default_branch: "main",
  settings: {},
  versions: [
    {
      ref: "v2.0.0",
      kind: "tag",
      commit_sha: SHA,
      imported_at: "2026-11-01T10:00:00Z",
      is_default: true,
    },
  ],
  default_version: "v2.0.0",
};

interface Options {
  status?: number;
  omitted?: number;
  complete?: boolean;
  empty?: boolean;
}

const versionBox = () => screen.findByRole("searchbox", { name: /^Search v/ });

const headerBox = async () =>
  (await screen.findAllByRole("searchbox", { name: "Search all libraries" }))[0] as HTMLElement;

function mount(path: string, options: Options = {}) {
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
      if (url.pathname.endsWith("/libraries/acme/payments/search")) {
        const results = [
          { ...hit("/acme/payments", 1), heading_path: ["Retries"], anchor: "retries" },
        ];
        return Response.json({
          notice: "",
          library: "/acme/payments",
          version: url.searchParams.get("ref"),
          commit_sha: SHA,
          retrieval_mode: "lexical",
          reranked: false,
          coverage: { candidates: 1, reranked: 0, complete: true },
          fallback_reason: null,
          results,
        });
      }
      if (url.pathname.endsWith("/articles"))
        return Response.json({ articles: [], next_cursor: null });
      if (url.pathname.endsWith("/tags")) return Response.json({ tags: [], truncated: false });
      if (url.pathname.endsWith("/libraries/acme/payments")) return Response.json(library);
      if (url.pathname.endsWith("/v1/search")) {
        if (options.status) {
          return Response.json({ error: "x", detail: "x", fields: [] }, { status: options.status });
        }
        const only = url.searchParams.get("library");
        const results = [hit("/acme/payments", 1), hit("/fixture/docs-repo", 2)].filter(
          (h) => !only || h.library === only,
        );
        if (options.empty) results.length = 0;
        return Response.json({
          notice: "",
          retrieval_mode: "bm25",
          reranked: false,
          coverage: { candidates: results.length, reranked: 0, complete: options.complete ?? true },
          libraries_searched: 2,
          libraries_omitted: options.omitted ?? 0,
          libraries: options.empty ? [] : facets,
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
  return {
    router,
    searches: () => calls.filter((u) => u.pathname.endsWith("/v1/search")),
  };
}

describe("searching all libraries", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("opens /search from the header box and keeps the query in the URL", async () => {
    const { router, searches } = mount("/account");
    const box = await headerBox();
    await userEvent.type(box, "token{Enter}");
    expect(await screen.findAllByRole("link", { name: /Tokens/ })).toHaveLength(2);
    expect(router.state.location.search).toMatchObject({ q: "token" });
    expect(searches()[0]?.searchParams.get("q")).toBe("token");
    expect(searches()[0]?.searchParams.has("library")).toBe(false);
  });

  it("narrows to one library while the counts stay", async () => {
    const { router, searches } = mount("/search?q=token");
    const facet = await screen.findByRole("link", { name: "/fixture/docs-repo, 1 match" });
    expect(screen.getByRole("link", { name: "All libraries, 4 matches" })).toBeVisible();
    await userEvent.click(facet);
    await waitFor(() =>
      expect(searches().at(-1)?.searchParams.get("library")).toBe("/fixture/docs-repo"),
    );
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Tokens/ })).toHaveLength(1));
    expect(router.state.location.search).toMatchObject({ library: "/fixture/docs-repo" });
    const nav = screen.getByRole("navigation", { name: "Libraries with matches" });
    expect(within(nav).getByRole("link", { name: "/acme/payments, 3 matches" })).toBeVisible();
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

  it("clears with Escape, and a new query drops the library", async () => {
    const { router } = mount("/search?q=token&library=/fixture/docs-repo");
    const box = await headerBox();
    expect(box).toHaveValue("token");
    await userEvent.type(box, "s{Enter}");
    await waitFor(() => expect(router.state.location.search).toEqual({ q: "tokens" }));
    await userEvent.clear(box);
    await userEvent.type(box, "{Escape}");
    await userEvent.type(box, "{Escape}");
    await waitFor(() => expect(router.state.location.search).toEqual({}));
    expect(await screen.findByText(/Searches the default version of every library/)).toBeVisible();
  });

  it("types without being overwritten, then Back restores the earlier query", async () => {
    const { router } = mount("/search?q=token");
    const box = await headerBox();
    await userEvent.type(box, "s{Enter}");
    await waitFor(() => expect(router.state.location.search).toEqual({ q: "tokens" }));
    await userEvent.type(box, "x");
    expect(box).toHaveValue("tokensx");
    router.history.back();
    await waitFor(() => expect(box).toHaveValue("token"));
  });

  it("gives `/` to the header box on a page without its own box", async () => {
    mount("/account");
    const box = await headerBox();
    await userEvent.keyboard("/");
    expect(box).toHaveFocus();
  });

  it("gives `/` to the version box on a library page, not the header box", async () => {
    mount("/libraries/acme/payments?version=v2.0.0");
    const header = await headerBox();
    const version = await versionBox();
    const headerFocused = vi.fn();
    header.addEventListener("focus", headerFocused);
    await userEvent.keyboard("/");
    expect(version).toHaveFocus();
    expect(headerFocused).not.toHaveBeenCalled();
  });

  it("ArrowDown in the header box on a library page stays out of the version's hits", async () => {
    mount("/libraries/acme/payments?version=v2.0.0&q=retry");
    const header = await headerBox();
    const results = await waitFor(() => {
      const el = document.getElementById("search-results");
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    await within(results).findByRole("link", { name: /Retries/ });
    header.focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(header).toHaveFocus();
    expect(document.activeElement?.closest("#search-results")).toBeNull();
  });

  it("replaces history while typing on /search, and Enter pushes one entry", async () => {
    const { router } = mount("/search?q=token");
    const box = await headerBox();
    await screen.findAllByRole("link", { name: /Tokens/ });
    const before = router.history.length;
    await userEvent.type(box, "s");
    await waitFor(() => expect(router.state.location.search).toEqual({ q: "tokens" }));
    expect(router.history.length).toBe(before);
    await userEvent.type(box, "x{Enter}");
    await waitFor(() => expect(router.state.location.search).toEqual({ q: "tokensx" }));
    expect(router.history.length).toBe(before + 1);
  });

  it("explains an omitted library and an incomplete list, and drops the facet hint when narrowed", async () => {
    mount("/search?q=token", { omitted: 2, complete: false });
    expect(await screen.findByText(/Searched 2 of 4 libraries/)).toBeVisible();
    expect(screen.getByRole("link", { name: /Browse them on the Libraries page/ })).toBeVisible();
    expect(screen.getByText(/use a library above/)).toBeVisible();
    expect(screen.getByText("Top 2 of 4")).toBeVisible();
  });

  it("drops the library hint when already narrowed", async () => {
    mount("/search?q=token&library=/acme/payments", { complete: false });
    expect(await screen.findByText(/use a more specific word\./)).toBeVisible();
    expect(screen.queryByText(/use a library above/)).toBeNull();
  });

  it("announces one sentence once settled, and marks the current facet", async () => {
    mount("/search?q=token&library=/acme/payments");
    await screen.findAllByRole("link", { name: /Tokens/ });
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "1 result for “token” in /acme/payments",
      ),
    );
    expect(screen.getByRole("link", { name: "/acme/payments, 3 matches" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("shows an empty state, with and without a library", async () => {
    mount("/search?q=zzz", { empty: true });
    expect(await screen.findByRole("heading", { name: "No results" })).toBeVisible();
    expect(screen.getByText(/open the library and use its search box/)).toBeVisible();
    expect(
      within(screen.getByRole("main")).queryByRole("link", { name: "Search all libraries" }),
    ).toBeNull();
    cleanup();
    mount("/search?q=zzz&library=/acme/payments", { empty: true });
    expect(
      await screen.findByRole("heading", { name: "No results in /acme/payments" }),
    ).toBeVisible();
    const all = within(screen.getByRole("main")).getByRole("link", {
      name: "Search all libraries",
    });
    expect(all).toHaveAttribute("href", "/search?q=zzz");
  });

  it("keeps the query behind the phone's search door on /search, and focuses the page box only without one", async () => {
    mount("/search?q=token");
    const door = within(await screen.findByRole("banner")).getByRole("link", {
      name: "Search all libraries",
    });
    await waitFor(() => expect(door).toHaveAttribute("href", "/search?q=token"));
    const [, page] = await screen.findAllByRole("searchbox", { name: "Search all libraries" });
    expect(page).not.toHaveFocus();
    cleanup();
    mount("/search");
    const [, empty] = await screen.findAllByRole("searchbox", { name: "Search all libraries" });
    await waitFor(() => expect(empty).toHaveFocus());
  });

  it("treats a 404 for an unknown library as an empty state, not a failure", async () => {
    mount("/search?q=token&library=/gone/lib", { status: 404 });
    expect(await screen.findByRole("heading", { name: "Library not available" })).toBeVisible();
    expect(within(screen.getByRole("main")).queryByRole("alert")).toBeNull();
    expect(
      within(screen.getByRole("main")).getByRole("link", { name: "Search all libraries" }),
    ).toBeVisible();
  });

  it("keeps Try again for server errors", async () => {
    mount("/search?q=token", { status: 500 });
    expect(
      await screen.findByRole("button", { name: "Try again" }, { timeout: 4000 }),
    ).toBeVisible();
  });

  it("ArrowDown in the header box moves into the global results", async () => {
    mount("/search?q=token");
    const box = await headerBox();
    await screen.findAllByRole("link", { name: /Tokens/ });
    box.focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement?.closest("#global-search-results")).not.toBeNull();
    await userEvent.keyboard("{ArrowUp}");
    expect(box).toHaveFocus();
  });
});
