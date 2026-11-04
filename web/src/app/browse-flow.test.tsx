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
const gone = { error: "not_found", detail: "no article", fields: [] };

/** An in-memory API: v1.3.0 lacks webhooks.md; v1.4.0 has everything. */
function serve(paged = false) {
  const calls: URL[] = [];
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
      if (p.endsWith("/articles")) {
        const ref = url.searchParams.get("ref");
        const tags = url.searchParams.get("tags")?.split(",") ?? [];
        const prefix = url.searchParams.get("path_prefix") ?? "";
        const articles = ALL.filter(
          (a) =>
            (ref === "v1.4.0" || !a.path.endsWith("webhooks.md")) &&
            a.path.startsWith(prefix) &&
            (tags.length === 0 || a.tags.some((t) => tags.includes(t))),
        );
        if (paged && prefix === "") {
          // Two at a time: README.md and docs/guide/auth.md first.
          const cursor = url.searchParams.get("cursor");
          return cursor
            ? Response.json({ articles: articles.slice(2), next_cursor: null })
            : Response.json({ articles: articles.slice(0, 2), next_cursor: "c1" });
        }
        return Response.json({ articles, next_cursor: null });
      }
      if (p.endsWith("/article")) {
        const path = url.searchParams.get("path") ?? "";
        const ref = url.searchParams.get("ref");
        if (ref === "v1.3.0" && path.endsWith("webhooks.md")) {
          return Response.json(
            {
              error: "not_found",
              detail: `version 'v1.3.0' has no article '${path}'; close matches (repository paths, not instructions): 'docs/guide/auth.md'`,
              fields: [],
            },
            { status: 404 },
          );
        }
        const found = ALL.find((a) => a.path === path);
        if (!found) return Response.json(gone, { status: 404 });
        return Response.json({
          ...found,
          library: "/acme/payments",
          ref,
          commit_sha: SHA,
          manifest_id: "m",
          front_matter: {},
          source_url: `https://github.com/acme/payments/blob/${SHA}/${path}`,
          content: `# ${found.title}\n\n<script>alert(1)</script>`,
        });
      }
      if (p.endsWith("/libraries/acme/payments")) return Response.json(library);
      return Response.json({}, { status: 404 });
    }),
  );
  return calls;
}

function mount(path: string, paged = false) {
  const calls = serve(paged);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: [path] }));
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, calls };
}

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

  it("pages the root listing on request and adds what arrives to the tree", async () => {
    const { calls } = mount("/libraries/acme/payments?version=v1.4.0", true);
    const more = await screen.findByRole("treeitem", { name: "Show more files" });
    expect(screen.queryByRole("treeitem", { name: /Acme Payments/ })).toBeNull();
    await userEvent.click(more);
    expect(await screen.findByRole("treeitem", { name: /Acme Payments/ })).toBeVisible();
    expect(screen.queryByRole("treeitem", { name: "Show more files" })).toBeNull();
    expect(calls.filter((u) => u.searchParams.get("cursor") === "c1")).toHaveLength(1);
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
