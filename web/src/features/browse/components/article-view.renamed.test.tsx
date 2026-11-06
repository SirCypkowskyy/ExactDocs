import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, type RouterHistory, useRouterState } from "@tanstack/react-router";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import type { Article, LibraryDetail, Version } from "../model/browse";
import { ArticleView } from "./article-view";

const SHA = "d".repeat(40);
const version = {
  ref: "v2.0.0",
  kind: "tag",
  commit_sha: SHA,
  imported_at: "2026-11-01T10:00:00Z",
  is_default: true,
} as Version;
const library = {
  id: "/acme/payments",
  title: "payments",
  source_url: "https://github.com/acme/payments",
  host: "github",
  versions: [version],
  default_version: "v2.0.0",
} as unknown as LibraryDetail;
const page = (path: string, title: string, content: string) =>
  ({
    path,
    title,
    tags: [],
    manual_tags: [],
    front_matter: {},
    source_url: null,
    content,
  }) as unknown as Article;
const articles: Record<string, Article> = {
  "docs/guide/intro.md": page(
    "docs/guide/intro.md",
    "Intro",
    "# Intro\n\nSee [setup](../setup.md#docker).\n",
  ),
  "docs/guide/setup.md": page(
    "docs/guide/setup.md",
    "Setup",
    "# Setup\n\n## Local\n\ntext\n\n## Docker\n\nrun it\n",
  ),
};
const moved = {
  library: "/acme/payments",
  ref: "v2.0.0",
  from_ref: "v1.0.0",
  old_path: "docs/setup.md",
  new_path: "docs/guide/setup.md",
  similarity: 100,
};

const json = (body: unknown, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
const notFound = () =>
  json({ error: "article_not_found", message: "No such article.", close_matches: [] }, 404);

/** The server: two articles, and a rename lookup answered by `renames`. */
function serve(renames: (url: URL) => Promise<Response>) {
  const fetch = vi.fn((input: string) => {
    const url = new URL(input, "http://x");
    if (url.pathname.endsWith("/access")) return json({ private: false });
    if (url.pathname.endsWith("/renamed-path")) return renames(url);
    const found = articles[url.searchParams.get("path") ?? ""];
    return found ? json(found) : notFound();
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

let client: QueryClient;

/** The library page: the article at the URL's `path`, re-mounted per path as the real page does. */
function Library() {
  const path = useRouterState({
    select: (s) => (s.location.search as { path?: string }).path ?? "",
  });
  return (
    <QueryClientProvider client={client}>
      <ArticleView
        key={path}
        owner="acme"
        repo="payments"
        library={library}
        version={version}
        path={path}
        tags={undefined}
      />
    </QueryClientProvider>
  );
}

let history: RouterHistory;

function view(path: string) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const start = `/libraries/acme/payments?version=v2.0.0&path=${encodeURIComponent(path)}`;
  history = createMemoryHistory({ initialEntries: [start] });
  return render(<TestRouter pages={{ "/libraries/$owner/$repo": Library }} history={history} />);
}

const at = () => new URLSearchParams(history.location.search).get("path");

beforeAll(() => import("../render/markdown"));
afterEach(() => vi.unstubAllGlobals());

describe("a relative link to a renamed article", () => {
  it("opens the new path in the same version, at the anchor", async () => {
    const fetch = serve(() => json({ renamed: moved }));
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
    view("docs/guide/intro.md");
    await userEvent.click(await screen.findByRole("link", { name: "setup" }));

    const docker = await screen.findByRole("heading", { name: /Docker/ });
    expect(screen.getByRole("heading", { level: 2, name: "Setup" })).toBeInTheDocument();
    expect(docker).toHaveClass("doc-target");
    expect(scroll.mock.contexts).toContain(docker);
    expect(screen.queryByText(/Not in/)).toBeNull();
    expect(screen.getByText(/Moved from/)).toHaveTextContent("Moved from docs/setup.md in v2.0.0");
    expect(at()).toBe("docs/guide/setup.md");
    expect(history.location.hash).toBe("#docker");
    const lookup = fetch.mock.calls
      .map(([u]) => new URL(u, "http://x"))
      .find((u) => u.pathname.endsWith("/renamed-path"));
    expect(Object.fromEntries(lookup?.searchParams ?? [])).toEqual({
      ref: "v2.0.0",
      path: "docs/setup.md",
      direction: "forward",
    });
    scroll.mockRestore();
  });

  it.each([
    ["no rename is known", () => json({ renamed: null })],
    [
      "the rename points back at the same path",
      () => json({ renamed: { ...moved, new_path: "docs/setup.md" } }),
    ],
    ["the lookup fails", () => json({ error: "internal", message: "boom" }, 500)],
  ])("%s: the page stays 'Not in this version', with the host link", async (_, answer) => {
    serve(answer);
    view("docs/setup.md");
    expect(await screen.findByRole("heading", { name: /Not in/ })).toHaveTextContent(
      "Not in v2.0.0",
    );
    expect(screen.getByRole("link", { name: /View on GitHub/ })).toHaveAttribute(
      "href",
      `https://github.com/acme/payments/blob/${SHA}/docs/setup.md`,
    );
  });

  it("Back from the redirected article returns to the linking one, not to the old path", async () => {
    serve(() => json({ renamed: moved }));
    view("docs/guide/intro.md");
    await userEvent.click(await screen.findByRole("link", { name: "setup" }));
    await screen.findByRole("heading", { name: /Docker/ });

    act(() => history.back());
    expect(await screen.findByRole("heading", { level: 2, name: "Intro" })).toBeInTheDocument();
    expect(at()).toBe("docs/guide/intro.md");
    expect(screen.queryByText(/Moved from/)).toBeNull();
    // and it stays there: the old path is not in the history to bounce through
    await new Promise((r) => setTimeout(r, 50));
    expect(at()).toBe("docs/guide/intro.md");
    expect(screen.getByRole("heading", { level: 2, name: "Intro" })).toBeInTheDocument();
  });

  it("does not ask for renames when the article is there, and says nothing about a move", async () => {
    const fetch = serve(() => json({ renamed: moved }));
    view("docs/guide/setup.md");
    await screen.findByRole("heading", { name: /Docker/ });
    expect(fetch.mock.calls.some(([u]) => u.includes("/renamed-path"))).toBe(false);
    expect(screen.queryByText(/Moved from/)).toBeNull();
  });
});
