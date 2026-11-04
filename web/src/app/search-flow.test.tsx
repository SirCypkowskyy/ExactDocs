import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAppRouter } from "./router";

const SHA = "2af418f7206a048fd5c2c0b4f06330b0dd48b0ff";
const version = (ref: string, is_default = false) => ({
  ref,
  kind: "tag",
  commit_sha: SHA,
  imported_at: "2026-11-01T10:00:00Z",
  is_default,
});
const library = {
  id: "/acme/payments",
  title: "Acme Payments",
  description: "",
  source_url: "https://github.com/acme/payments.git",
  host: "github",
  default_branch: "main",
  settings: {},
  versions: [version("v1.3.0"), version("v1.4.0", true)],
  default_version: "v1.4.0",
};

const hit = (n: number, over: Record<string, unknown> = {}) => ({
  chunk_id: `c${n}`,
  article_path: "docs/guide/retries.md",
  heading_path: ["Retries", "Policy"],
  anchor: "policy",
  position: n,
  total: 9,
  prev_chunk_id: null,
  next_chunk_id: null,
  commit_sha: SHA,
  source_url: `https://github.com/acme/payments/blob/${SHA}/docs/guide/retries.md#policy`,
  tags: ["api"],
  score: 1,
  snippet: "Set retry_policy to control backoff.",
  highlights: [{ start: 4, end: 16 }],
  ...over,
});

interface Options {
  /** Hits per version: v1.3.0 has none by default. */
  hits?: Record<string, unknown[]>;
  complete?: boolean;
  failSearch?: boolean;
}

function mount(path: string, options: Options = {}) {
  const calls: URL[] = [];
  let failing = options.failSearch ?? false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = new URL(input, "http://x");
      calls.push(url);
      const p = url.pathname;
      if (p.endsWith("/session")) {
        return Response.json({
          state: "signed_in",
          account: { id: "1", username: "ada", role: "admin" },
        });
      }
      if (p.endsWith("/search")) {
        if (failing) {
          failing = false;
          return Response.json({ error: "boom", detail: "boom", fields: [] }, { status: 500 });
        }
        const ref = url.searchParams.get("ref") ?? "";
        const results = (options.hits ?? { "v1.4.0": [hit(1)] })[ref] ?? [];
        return Response.json({
          notice: "",
          library: "/acme/payments",
          version: ref,
          commit_sha: SHA,
          retrieval_mode: "lexical",
          reranked: false,
          coverage: { candidates: results.length, reranked: 0, complete: options.complete ?? true },
          fallback_reason: null,
          results,
        });
      }
      if (p.endsWith("/articles")) return Response.json({ articles: [], next_cursor: null });
      if (p.endsWith("/tags")) {
        return Response.json({
          tags: [
            { tag: "api", count: 3 },
            { tag: "guide", count: 2 },
          ],
          truncated: false,
        });
      }
      if (p.endsWith("/article")) {
        return Response.json({
          path: "docs/guide/retries.md",
          title: "Retries",
          tags: [],
          size: 10,
          library: "/acme/payments",
          ref: url.searchParams.get("ref"),
          commit_sha: SHA,
          manifest_id: "m",
          front_matter: {},
          source_url: null,
          content: "# Retries",
        });
      }
      if (p.endsWith("/libraries/acme/payments")) return Response.json(library);
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
  return { router, searches: () => calls.filter((u) => u.pathname.endsWith("/search")) };
}

describe("searching a version", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the overview and no results while the query is empty", async () => {
    const { searches } = mount("/libraries/acme/payments?version=v1.4.0");
    expect(await screen.findByRole("searchbox", { name: "Search v1.4.0" })).toHaveValue("");
    expect(screen.getByText(/Pick a file from the tree/)).toBeVisible();
    expect(searches()).toHaveLength(0);
  });

  it("highlights the matched words from offsets and shows server text as text", async () => {
    mount("/libraries/acme/payments?version=v1.4.0&q=retry_policy", {
      hits: {
        "v1.4.0": [
          hit(1),
          hit(2, {
            heading_path: [],
            snippet: "🚀 <b>retry_policy</b> <script>alert(1)</script>",
            highlights: [{ start: 2, end: 21 }],
          }),
        ],
      },
    });
    const list = (await screen.findAllByRole("link", { name: /Retries/ }))[0];
    expect(list).toHaveTextContent("Retries›Policy");
    const marks = document.querySelectorAll("mark");
    expect([...marks].map((m) => m.textContent)).toEqual(["retry_policy", "<b>retry_policy</b>"]);
    expect(document.querySelector("b, script")).toBeNull();
    expect(screen.getByText(/alert\(1\)/)).toBeVisible();
  });

  it("scopes the search to the selected version and says when nothing matches", async () => {
    const { searches } = mount("/libraries/acme/payments?version=v1.3.0&q=retry_policy");
    expect(await screen.findByRole("heading", { name: "No results in v1.3.0" })).toBeVisible();
    expect(searches()[0]?.searchParams.get("ref")).toBe("v1.3.0");
    expect(searches()[0]?.searchParams.get("q")).toBe("retry_policy");
    await userEvent.click(screen.getByRole("link", { name: "Try v1.4.0" }));
    expect(await screen.findByRole("link", { name: /Retries/ })).toHaveTextContent(
      "Set retry_policy to control backoff.",
    );
    expect(searches().at(-1)?.searchParams.get("ref")).toBe("v1.4.0");
  });

  it("offers to drop the tag filter when the tags leave nothing", async () => {
    const { router } = mount("/libraries/acme/payments?version=v1.3.0&q=zzz&tags=api");
    await userEvent.click(await screen.findByRole("button", { name: "Remove tag filter" }));
    await waitFor(() => expect(router.state.location.search).not.toHaveProperty("tags"));
  });

  it("opens the article at the heading anchor", async () => {
    const { router } = mount("/libraries/acme/payments?version=v1.4.0&q=retry_policy");
    await userEvent.click(await screen.findByRole("link", { name: /Retries/ }));
    expect(router.state.location.search).toMatchObject({
      version: "v1.4.0",
      path: "docs/guide/retries.md",
    });
    expect(router.state.location.hash).toBe("policy");
    expect(await screen.findByRole("heading", { name: "Retries", level: 2 })).toBeVisible();
  });

  it("keeps the query in the URL after a pause, and clears it with Escape", async () => {
    const { router, searches } = mount("/libraries/acme/payments?version=v1.4.0");
    const box = await screen.findByRole("searchbox");
    await userEvent.type(box, "retry");
    expect(searches()).toHaveLength(0);
    await waitFor(() => expect(router.state.location.search).toMatchObject({ q: "retry" }));
    expect(await screen.findByText("1 result for “retry” in v1.4.0")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(router.state.location.search).not.toHaveProperty("q"));
    expect(box).toHaveValue("");
  });

  it("combines tags with any or all, and sends the caps", async () => {
    const { searches } = mount("/libraries/acme/payments?version=v1.4.0&q=retry&tags=api,guide");
    await screen.findByRole("button", { name: "Any of" });
    expect(searches().at(-1)?.searchParams.get("tags_match")).toBe("any");
    await userEvent.click(screen.getByRole("button", { name: "All of" }));
    await waitFor(() => expect(searches().at(-1)?.searchParams.get("tags_match")).toBe("all"));
    expect(searches().at(-1)?.searchParams.get("tags")).toBe("api,guide");
    expect(searches().at(-1)?.searchParams.get("limit")).toBe("20");
  });

  it("focuses the box with / and walks the results with the arrow keys", async () => {
    mount("/libraries/acme/payments?version=v1.4.0&q=retry", {
      hits: { "v1.4.0": [hit(1), hit(2, { anchor: "backoff", heading_path: ["Backoff"] })] },
    });
    const box = await screen.findByRole("searchbox");
    await screen.findByRole("link", { name: /Backoff/ });
    await userEvent.keyboard("/");
    expect(box).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    const results = within(document.getElementById("search-results") as HTMLElement);
    const [first, second] = results.getAllByRole("link", { name: /Retries|Backoff/ });
    expect(first).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(second).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}{ArrowUp}");
    expect(box).toHaveFocus();
  });

  it("says the list is cut when more sections match", async () => {
    mount("/libraries/acme/payments?version=v1.4.0&q=retry", { complete: false });
    expect(await screen.findByText(/Showing the best 1/)).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Top 1 result");
  });

  it("reports a failed search and retries", async () => {
    mount("/libraries/acme/payments?version=v1.4.0&q=retry", { failSearch: true });
    expect(await screen.findByRole("heading", { name: "Search failed" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: /Retries/ })).toBeVisible();
  });
});
