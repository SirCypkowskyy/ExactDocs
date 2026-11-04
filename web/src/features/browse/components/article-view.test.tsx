import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import type { Article, LibraryDetail, Version } from "../model/browse";
import { ArticleView } from "./article-view";

const SHA = "b".repeat(40);
const version = {
  ref: "v1.0.0",
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
  default_version: "v1.0.0",
} as unknown as LibraryDetail;
const article = {
  path: "docs/start.md",
  title: "Start",
  tags: [],
  source_url: null,
  content:
    "# Start\n\n## Install\n\n![Shot](./shot.png)\n\n> [!NOTE]\n> Mind the gap.\n\n<script>alert(1)</script>\n",
} as unknown as Article;

function serve(isPrivate: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        new Response(JSON.stringify(url.includes("/access") ? { private: isPrivate } : article), {
          headers: { "content-type": "application/json" },
        }),
      ),
    ),
  );
}

let client: QueryClient;

function Page() {
  return (
    <QueryClientProvider client={client}>
      <ArticleView
        owner="acme"
        repo="payments"
        library={library}
        version={version}
        path="docs/start.md"
        tags={undefined}
      />
    </QueryClientProvider>
  );
}

function view(start = "/") {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<TestRouter pages={{ "/": Page }} start={start} />);
}

afterEach(() => vi.unstubAllGlobals());

describe("ArticleView", () => {
  it("renders the article, with the repository's image at the commit when the library is public", async () => {
    serve(false);
    view();
    expect(await screen.findByRole("heading", { name: /Install/ })).toHaveAttribute(
      "id",
      "doc-install",
    );
    expect(screen.getByRole("note")).toHaveTextContent("Mind the gap.");
    expect(await screen.findByRole("img", { name: "Shot" })).toHaveAttribute(
      "src",
      `https://raw.githubusercontent.com/acme/payments/${SHA}/docs/shot.png`,
    );
    expect(document.querySelector("script")).toBeNull();
  });

  it("shows only the alt text of an image in a private library", async () => {
    serve(true);
    view();
    await screen.findByRole("heading", { name: /Install/ });
    expect(screen.queryByRole("img", { name: "Shot" })).toBeNull();
    expect(screen.getByText("Image not shown: Shot")).toBeInTheDocument();
  });

  it("keeps the file as stored one click away", async () => {
    serve(false);
    view();
    await screen.findByRole("heading", { name: /Install/ });
    await userEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.getByRole("region", { name: "Source text" })).toHaveTextContent(
      "![Shot](./shot.png)",
    );
    expect(screen.queryByRole("heading", { name: /Install/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Rendered" }));
    expect(await screen.findByRole("heading", { name: /Install/ })).toBeInTheDocument();
  });

  it("lands on the heading a search result links to (the bare chunk anchor as the URL hash)", async () => {
    serve(false);
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
    view("/#install");
    const heading = await screen.findByRole("heading", { name: /Install/ });
    expect(heading).toHaveAttribute("id", "doc-install");
    expect(heading).toHaveClass("doc-target");
    expect(scroll.mock.contexts).toContain(heading);
    scroll.mockRestore();
  });
});
