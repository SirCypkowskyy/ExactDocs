import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
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

function view(path: string) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const start = `/libraries/acme/payments?version=v2.0.0&path=${encodeURIComponent(path)}`;
  return render(<TestRouter pages={{ "/libraries/$owner/$repo": Library }} start={start} />);
}

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
    ["the rename map is from another version", () => json({ renamed: { ...moved, ref: "v3" } })],
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

  it("does not ask for renames when the article is there", async () => {
    const fetch = serve(() => json({ renamed: moved }));
    view("docs/guide/setup.md");
    await screen.findByRole("heading", { name: /Docker/ });
    expect(fetch.mock.calls.some(([u]) => u.includes("/renamed-path"))).toBe(false);
  });
});
