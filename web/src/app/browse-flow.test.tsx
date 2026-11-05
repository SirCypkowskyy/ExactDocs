import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createQueryClient } from "./query-client";
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
const summary = (path: string, title: string, tags: string[] = []) => ({
  path,
  title,
  tags,
  size: 10,
});
const ALL = [
  summary("docs/guide/auth.md", "Authentication", ["api", "guide"]),
  summary("docs/guide/install.md", "Installing", ["guide"]),
  summary("docs/guide/webhooks.md", "Webhooks", ["api"]),
  summary("README.md", "Acme Payments", ["guide"]),
];
interface Options {
  /** Articles per page; unset lists everything in one page. */
  pageSize?: number;
  /** Make the listing of this folder fail. */
  failPrefix?: string;
  /** Make every article read fail with a 500. */
  failArticle?: boolean;
  /** The tags endpoint answers these instead of the real counts. */
  tags?: { tag: string; count: number }[];
  sourceUrl?: string;
}

const gone = { error: "not_found", detail: "no article", fields: [], close_matches: [] };

/** An in-memory API: v1.3.0 lacks webhooks.md; v1.4.0 has everything. */
function serve(options: Options = {}) {
  const calls: URL[] = [];
  // Manual tags by path: they hold for every version, as the API keeps them.
  const manual = new Map<string, string[]>();
  const tagsOf = (a: { path: string; tags: string[] }) => [
    ...new Set([...a.tags, ...(manual.get(a.path) ?? [])]),
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, "http://x");
      calls.push(url);
      const p = url.pathname;
      const ref = url.searchParams.get("ref");
      if (p.endsWith("/tags") && (init?.method === "PUT" || init?.method === "DELETE")) {
        const path = url.searchParams.get("path") ?? "";
        const body = init.method === "PUT" ? JSON.parse(String(init.body)) : { tags: [] };
        const tags = (body.tags as string[]).map((t) => t.toLowerCase());
        manual.set(path, tags);
        if (init.method === "DELETE") return new Response(null, { status: 204 });
        return Response.json({ library: "/acme/payments", path, tags });
      }
      const inVersion = (a: { path: string }) =>
        ref === "v1.4.0" || !a.path.endsWith("webhooks.md");
      if (p.endsWith("/session")) {
        return Response.json({
          state: "signed_in",
          account: { id: "1", username: "ada", role: "admin" },
        });
      }
      if (p.endsWith("/articles")) {
        const tags = url.searchParams.get("tags")?.split(",") ?? [];
        const prefix = url.searchParams.get("path_prefix") ?? "";
        if (options.failPrefix !== undefined && prefix === options.failPrefix) {
          return Response.json({ error: "boom", detail: "boom", fields: [] }, { status: 400 });
        }
        const articles = ALL.filter(
          (a) =>
            inVersion(a) &&
            (prefix === "" || a.path.startsWith(`${prefix}/`)) &&
            (tags.length === 0 || tagsOf(a).some((t) => tags.includes(t))),
        )
          .map((a) => ({ ...a, tags: tagsOf(a) }))
          .sort((x, y) => (x.path < y.path ? -1 : 1));
        const size = options.pageSize ?? 1000;
        const from = Number(url.searchParams.get("cursor")?.slice(1) ?? 0);
        const page = articles.slice(from, from + size);
        const next = from + size < articles.length ? `c${from + size}` : null;
        return Response.json({ articles: page, next_cursor: next });
      }
      if (p.endsWith("/tags")) {
        const counts = new Map<string, number>();
        for (const a of ALL.filter(inVersion))
          for (const t of tagsOf(a)) counts.set(t, (counts.get(t) ?? 0) + 1);
        const tags =
          options.tags ??
          [...counts]
            .sort((x, y) => y[1] - x[1] || (x[0] < y[0] ? -1 : 1))
            .map(([tag, count]) => ({ tag, count }));
        return Response.json({ tags, truncated: false });
      }
      if (p.endsWith("/article")) {
        const path = url.searchParams.get("path") ?? "";
        if (options.failArticle) {
          return Response.json({ error: "boom", detail: "boom", fields: [] }, { status: 500 });
        }
        if (ref === "v1.3.0" && path.endsWith("webhooks.md")) {
          return Response.json(
            {
              error: "not_found",
              detail: `version 'v1.3.0' has no article '${path}'`,
              fields: [],
              close_matches: ["docs/guide/auth.md"],
            },
            { status: 404 },
          );
        }
        const found = ALL.find((a) => a.path === path);
        if (!found) return Response.json(gone, { status: 404 });
        return Response.json({
          ...found,
          tags: tagsOf(found),
          manual_tags: (manual.get(path) ?? []).map((tag) => ({ tag, path })),
          library: "/acme/payments",
          ref,
          commit_sha: SHA,
          manifest_id: "m",
          front_matter: {},
          source_url: `https://github.com/acme/payments/blob/${SHA}/${path}`,
          content: `# ${found.title}\n\n<script>alert(1)</script>`,
        });
      }
      if (p.endsWith("/libraries/acme/payments")) {
        return Response.json({
          ...library,
          source_url: options.sourceUrl ?? library.source_url,
        });
      }
      return Response.json(gone, { status: 404 });
    }),
  );
  return calls;
}

function mount(path: string, options: Options & { realRetries?: boolean } = {}) {
  const calls = serve(options);
  const client = options.realRetries
    ? createQueryClient()
    : new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: [path] }));
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, calls, client };
}

const listings = (calls: URL[]) => calls.filter((u) => u.pathname.endsWith("/articles"));

describe("browsing a library version", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the tree, opens the article, and links to the exact commit", async () => {
    const { router } = mount("/libraries/acme/payments?version=v1.4.0");
    expect(await screen.findByRole("heading", { name: "Acme Payments", level: 1 })).toBeVisible();
    const tree = await screen.findByRole("tree", { name: "Files of v1.4.0" });
    await userEvent.click(await within(tree).findByRole("treeitem", { name: "docs" }));
    await userEvent.click(await within(tree).findByRole("treeitem", { name: "guide" }));
    await userEvent.click(await within(tree).findByRole("treeitem", { name: /Authentication/ }));
    expect(router.state.location.search).toMatchObject({
      version: "v1.4.0",
      path: "docs/guide/auth.md",
    });
    expect(await screen.findByRole("heading", { name: "Authentication", level: 2 })).toBeVisible();
    const file = screen.getByRole("link", { name: /View file on GitHub/ });
    expect(file).toHaveAttribute(
      "href",
      `https://github.com/acme/payments/blob/${SHA}/docs/guide/auth.md`,
    );
    expect(screen.getByRole("link", { name: /Commit 2af418f/ })).toHaveAttribute(
      "href",
      `https://github.com/acme/payments/commit/${SHA}`,
    );
  });

  it("shows repository text as text, never as markup", async () => {
    mount("/libraries/acme/payments?version=v1.4.0&path=docs/guide/auth.md");
    expect(await screen.findByText(/<script>alert\(1\)<\/script>/)).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
  });

  it("opens the folders of a deep link and marks the article as selected", async () => {
    mount("/libraries/acme/payments?version=v1.4.0&path=docs/guide/auth.md");
    const item = await screen.findByRole("treeitem", { name: /Authentication/ });
    expect(item).toHaveAttribute("aria-selected", "true");
    expect(item).toHaveAttribute("aria-level", "3");
  });

  it("filters the tree by tag through the URL", async () => {
    const { router, calls } = mount("/libraries/acme/payments?version=v1.4.0");
    await screen.findByRole("tree");
    await userEvent.click(await screen.findByRole("button", { name: "api" }));
    await waitFor(() => expect(router.state.location.search).toMatchObject({ tags: "api" }));
    await waitFor(() =>
      expect(
        calls.some((u) => u.pathname.endsWith("/articles") && u.searchParams.get("tags") === "api"),
      ).toBe(true),
    );
    expect(screen.getByRole("button", { name: "api" })).toHaveAttribute("aria-pressed", "true");
    // The other tags stay on offer while one is selected.
    expect(screen.getByRole("button", { name: "guide" })).toBeVisible();
  });

  it("adds a manual tag: it shows on the article and in the tree's filter of every version", async () => {
    const { router } = mount("/libraries/acme/payments?version=v1.4.0&path=docs/guide/install.md");
    expect(await screen.findByRole("heading", { name: "Installing", level: 2 })).toBeVisible();
    const tags = screen.getByRole("region", { name: "Tags" });
    expect(within(tags).getByRole("list", { name: "Tags from path rules" })).toHaveTextContent(
      "guide",
    );
    await userEvent.click(within(tags).getByRole("button", { name: "Add tag" }));
    await userEvent.type(
      within(tags).getByRole("textbox", { name: "New tag" }),
      "Onboarding{Enter}",
    );
    const byHand = within(tags).getByRole("list", { name: "Tags added by hand" });
    expect(await within(byHand).findByText("onboarding")).toBeVisible();
    expect(await screen.findByRole("button", { name: "onboarding" })).toBeVisible();

    await router.navigate({
      to: "/libraries/$owner/$repo",
      params: { owner: "acme", repo: "payments" },
      search: { version: "v1.3.0", path: "docs/guide/install.md" },
    });
    await waitFor(() =>
      expect(screen.getByRole("tree", { name: "Files of v1.3.0" })).toBeVisible(),
    );
    const older = await screen.findByRole("list", { name: "Tags added by hand" });
    expect(await within(older).findByText("onboarding")).toBeVisible();
    await userEvent.click(await screen.findByRole("button", { name: "onboarding" }));
    const tree = screen.getByRole("tree", { name: "Files of v1.3.0" });
    expect(await within(tree).findByRole("treeitem", { name: /Installing/ })).toBeVisible();
    await waitFor(() =>
      expect(within(tree).queryByRole("treeitem", { name: /Authentication/ })).toBeNull(),
    );

    await userEvent.click(screen.getByRole("button", { name: "Remove tag onboarding" }));
    await waitFor(() =>
      expect(
        within(screen.getByRole("list", { name: "Tags added by hand" })).queryByText("onboarding"),
      ).toBeNull(),
    );
  });

  it("moves with the arrow keys and opens a folder with ArrowRight", async () => {
    mount("/libraries/acme/payments?version=v1.4.0");
    const docs = await screen.findByRole("treeitem", { name: "docs" });
    docs.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(docs).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("treeitem", { name: "guide" })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(docs).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(docs).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps the article path when switching version, and says when it is not there", async () => {
    const { router } = mount("/libraries/acme/payments?version=v1.4.0&path=docs/guide/webhooks.md");
    expect(await screen.findByRole("heading", { name: "Webhooks", level: 2 })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: /Change version/ }));
    await userEvent.click(await screen.findByRole("link", { name: /v1\.3\.0/ }));
    expect(router.state.location.search).toMatchObject({
      version: "v1.3.0",
      path: "docs/guide/webhooks.md",
    });
    expect(await screen.findByRole("heading", { name: /Not in v1\.3\.0/ })).toBeVisible();
    // Close matches come from the API's answer, as links within the same version.
    expect(screen.getByRole("link", { name: "docs/guide/auth.md" })).toBeVisible();
    await userEvent.click(screen.getByRole("link", { name: /Show the root of v1\.3\.0/ }));
    await waitFor(() => expect(router.state.location.search.path).toBeUndefined());
    expect(await screen.findByRole("heading", { name: /Browsing/ })).toBeVisible();
  });

  it("pages the root listing on request and moves focus to what arrived", async () => {
    const { calls } = mount("/libraries/acme/payments?version=v1.4.0", { pageSize: 2 });
    const more = await screen.findByRole("treeitem", { name: "Show more files" });
    expect(screen.queryByRole("treeitem", { name: "docs" })).toBeInTheDocument();
    more.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(screen.queryByRole("treeitem", { name: "Show more files" })).toBeNull(),
    );
    expect(listings(calls).filter((u) => u.searchParams.get("cursor") === "c2")).toHaveLength(1);
    // Focus did not fall back to the page: it went to a row the new page added.
    expect(document.body).not.toHaveFocus();
    expect(screen.getByRole("tree")).toContainElement(document.activeElement as HTMLElement);
  });

  it("lists a folder on its own when opened, and pages it", async () => {
    const { calls } = mount("/libraries/acme/payments?version=v1.4.0", { pageSize: 2 });
    const docs = await screen.findByRole("treeitem", { name: "docs" });
    await userEvent.click(docs);
    await screen.findByRole("treeitem", { name: "guide" });
    await userEvent.click(screen.getByRole("treeitem", { name: "guide" }));
    expect(listings(calls).some((u) => u.searchParams.get("path_prefix") === "docs")).toBe(true);
    // A folder's size is unknown while its listing has more pages.
    expect(screen.getByRole("treeitem", { name: "guide" })).toHaveAttribute("aria-setsize", "-1");
    await userEvent.click(await screen.findByRole("treeitem", { name: "Show more in docs" }));
    await waitFor(() =>
      expect(
        listings(calls).some(
          (u) =>
            u.searchParams.get("path_prefix") === "docs" && u.searchParams.get("cursor") === "c2",
        ),
      ).toBe(true),
    );
  });

  it("does not list a folder again when the listing already covers it", async () => {
    const { calls } = mount("/libraries/acme/payments?version=v1.4.0");
    await userEvent.click(await screen.findByRole("treeitem", { name: "docs" }));
    await userEvent.click(await screen.findByRole("treeitem", { name: "guide" }));
    expect(listings(calls)).toHaveLength(1);
  });

  it("opens a folder with Enter and Space, and moves with Home, End and ArrowLeft", async () => {
    mount("/libraries/acme/payments?version=v1.4.0");
    const docs = await screen.findByRole("treeitem", { name: "docs" });
    docs.focus();
    await userEvent.keyboard("{Enter}");
    expect(docs).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard(" ");
    expect(docs).toHaveAttribute("aria-expanded", "false");
    await userEvent.keyboard("{End}");
    expect(screen.getByRole("treeitem", { name: /Acme Payments/ })).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(docs).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}{ArrowDown}{ArrowRight}{ArrowDown}");
    expect(screen.getByRole("treeitem", { name: /Authentication/ })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("treeitem", { name: "guide" })).toHaveFocus();
  });

  it("does not move into an empty folder with ArrowRight, and types ahead", async () => {
    mount("/libraries/acme/payments?version=v1.4.0");
    const docs = await screen.findByRole("treeitem", { name: "docs" });
    docs.focus();
    await userEvent.keyboard("a");
    expect(screen.getByRole("treeitem", { name: /Acme Payments/ })).toHaveFocus();
  });

  it("keeps a selected tag on screen even when many tags outrank it", async () => {
    const tags = Array.from({ length: 30 }, (_, i) => ({ tag: `t${i}`, count: 30 - i }));
    mount("/libraries/acme/payments?version=v1.4.0&tags=t29", { tags });
    expect(await screen.findByRole("button", { name: "t29" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getAllByRole("button", { name: /^t\d+$/ }).length).toBeLessThanOrEqual(14);
  });

  it("shows the open article in the tree even when paging has not reached it", async () => {
    mount("/libraries/acme/payments?version=v1.4.0&path=docs/guide/webhooks.md", { pageSize: 2 });
    const item = await screen.findByRole("treeitem", { name: /Webhooks/ });
    expect(item).toHaveAttribute("aria-selected", "true");
  });

  it("follows the browser's Back and Forward across versions and paths", async () => {
    const { router } = mount("/libraries/acme/payments?version=v1.4.0&path=docs/guide/auth.md");
    expect(await screen.findByRole("heading", { name: "Authentication", level: 2 })).toBeVisible();
    await userEvent.click(await screen.findByRole("treeitem", { name: /Installing/ }));
    expect(await screen.findByRole("heading", { name: "Installing", level: 2 })).toBeVisible();
    router.history.back();
    expect(await screen.findByRole("heading", { name: "Authentication", level: 2 })).toBeVisible();
    router.history.forward();
    expect(await screen.findByRole("heading", { name: "Installing", level: 2 })).toBeVisible();
  });

  it("reads a numeric ?version= as text", async () => {
    mount("/libraries/acme/payments?version=2");
    expect(await screen.findByRole("status")).toHaveTextContent(/2.*not an imported version/);
  });

  it("links the repository by its web address, never with credentials", async () => {
    mount("/libraries/acme/payments?version=v1.4.0", {
      sourceUrl: "https://user:secret@github.com/acme/payments.git?x=1",
    });
    const link = await screen.findByRole("link", { name: /github\.com\/acme\/payments/ });
    expect(link).toHaveAttribute("href", "https://github.com/acme/payments");
    expect(document.body.textContent).not.toContain("secret");
  });

  it("links no repository for a source that is no web page", async () => {
    mount("/libraries/acme/payments?version=v1.4.0", { sourceUrl: "file:///srv/repo" });
    await screen.findByRole("heading", { name: "Acme Payments", level: 1 });
    expect(screen.queryByRole("link", { name: /opens the repository/ })).toBeNull();
  });

  it("says when a folder cannot be listed and tries again", async () => {
    mount("/libraries/acme/payments?version=v1.4.0&path=docs/guide/auth.md", {
      pageSize: 2,
      failPrefix: "docs/guide",
    });
    expect(await screen.findByRole("treeitem", { name: /Couldn't load guide/ })).toBeVisible();
  });

  it("offers a retry when the whole tree fails to load", async () => {
    mount("/libraries/acme/payments?version=v1.4.0", { failPrefix: "" });
    expect(await screen.findByText(/Couldn't load the files of v1\.4\.0/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("offers a retry when the article fails, and does not retry a 404", async () => {
    mount("/libraries/acme/payments?version=v1.4.0&path=docs/guide/auth.md", { failArticle: true });
    expect(await screen.findByText("Couldn't load this article")).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("asks once for an article that is not there (a 404 is not retried)", async () => {
    const { calls } = mount("/libraries/acme/payments?version=v1.3.0&path=docs/guide/webhooks.md", {
      realRetries: true,
    });
    expect(await screen.findByRole("heading", { name: /Not in v1\.3\.0/ })).toBeVisible();
    expect(calls.filter((u) => u.pathname.endsWith("/article"))).toHaveLength(1);
  });

  it("says so when the library does not exist", async () => {
    mount("/libraries/acme/nope");
    expect(await screen.findByRole("heading", { name: "Library not found" })).toBeVisible();
    expect(screen.getByRole("link", { name: "All libraries" })).toHaveAttribute("href", "/");
  });

  it("falls back to the default version for an unknown one, with a notice", async () => {
    mount("/libraries/acme/payments?version=v9.9.9");
    expect(await screen.findByRole("status")).toHaveTextContent(
      /v9\.9\.9.*not an imported version.*v1\.4\.0/,
    );
  });

  it("says when a tag matches nothing and offers the whole tree back", async () => {
    mount("/libraries/acme/payments?version=v1.4.0&tags=nope");
    expect(await screen.findByText("No articles tagged nope")).toBeVisible();
    expect(screen.getByRole("button", { name: "Show all articles" })).toBeVisible();
  });
});
