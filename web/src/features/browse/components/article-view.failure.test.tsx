import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import type { Article, LibraryDetail, Version } from "../model/browse";
import { ArticleView } from "./article-view";

// The renderer's chunk fails to load the first time, and loads the second.
const state = vi.hoisted(() => ({ attempts: 0 }));
vi.mock("../render/markdown", async (importOriginal) => {
  const real = await importOriginal<typeof import("../render/markdown")>();
  return {
    get Markdown() {
      if (state.attempts++ === 0) throw new Error("Failed to fetch dynamically imported module");
      return real.Markdown;
    },
  };
});

const version = {
  ref: "v1",
  kind: "tag",
  commit_sha: "c".repeat(40),
  imported_at: "2026-11-01T10:00:00Z",
  is_default: true,
} as Version;
const library = {
  id: "/a/b",
  title: "b",
  source_url: "https://github.com/a/b",
  host: "github",
  versions: [version],
  default_version: "v1",
} as unknown as LibraryDetail;
const content = `# Title\n\n## Part\n\nbody\n`;
const article = {
  path: "a.md",
  title: "Title",
  tags: [],
  tag_origins: [],
  manual_tags: [],
  front_matter: {},
  source_url: null,
  content,
} as unknown as Article;

let client: QueryClient;
function Page() {
  return (
    <QueryClientProvider client={client}>
      <ArticleView
        owner="a"
        repo="b"
        library={library}
        version={version}
        path="a.md"
        tags={undefined}
      />
    </QueryClientProvider>
  );
}

afterEach(() => vi.unstubAllGlobals());

function open(text = content) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.includes("/access") ? { private: false } : { ...article, content: text },
          ),
          {
            headers: { "content-type": "application/json" },
          },
        ),
      ),
    ),
  );
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<TestRouter pages={{ "/": Page }} />);
}

it("keeps the page when the renderer fails to load, and offers the source and a real retry", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  open();
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Couldn't load the article renderer");
  // the rest of the article is still there
  expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Source" })).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("heading", { name: /Part/ })).toHaveAttribute("id", "doc-part");
  expect(screen.queryByRole("alert")).toBeNull();
});

it("falls back to the source view", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  state.attempts = 0;
  open();
  await userEvent.click(await screen.findByRole("button", { name: "View source" }));
  expect(screen.getByRole("region", { name: "Source text" })).toHaveTextContent("## Part");
});

it("opens a very large file as source, with a way to render it", async () => {
  state.attempts = 1; // the renderer loads
  open(`# Big\n\n${"word ".repeat(90_000)}\n\n## Tail\n`);
  expect(await screen.findByRole("region", { name: "Source text" })).toHaveTextContent(
    "so it opens as source",
  );
  await userEvent.click(screen.getByRole("button", { name: "Render it anyway" }));
  expect(await screen.findByRole("heading", { name: /Tail/ })).toBeInTheDocument();
});
