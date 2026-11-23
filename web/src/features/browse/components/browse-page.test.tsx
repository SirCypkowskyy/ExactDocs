import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { BrowsePage } from "./browse-page";
import { BrowseSkeleton } from "./browse-skeleton";

const library = {
  id: "/acme/payments",
  title: "Acme Payments",
  description: "",
  source_url: "https://github.com/acme/payments",
  host: "github",
  default_branch: "main",
  default_pinned: false,
  settings: {},
  versions: [
    {
      ref: "v1.4.0",
      kind: "tag",
      commit_sha: "2af418f7206a048fd5c2c0b4f06330b0dd48b0ff",
      imported_at: "2026-11-01T10:00:00Z",
      is_default: true,
    },
  ],
  default_version: "v1.4.0",
};

let shown: () => React.ReactNode = () => null;
let client: QueryClient;

function Wrapped() {
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <Suspense fallback={null}>{shown()}</Suspense>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

function show(page: () => React.ReactNode) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  shown = page;
  render(<TestRouter pages={{ "/": Wrapped }} />);
}

describe("the library page", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("leads with the shared breadcrumb: back to the libraries, then the library ID", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const { pathname } = new URL(input, "http://test");
        if (pathname.endsWith("/articles"))
          return Response.json({ articles: [], next_cursor: null, total: 0 });
        if (pathname.endsWith("/tags")) return Response.json({ tags: [], truncated: false });
        return Response.json(library);
      }),
    );
    show(() => <BrowsePage owner="acme" repo="payments" search={{}} />);
    const crumbs = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Libraries" })).toHaveAttribute("href", "/");
    expect(within(crumbs).getByText("/acme/payments")).toHaveAttribute("aria-current", "page");
    // An imported version with no articles says so in the table's frame.
    expect(await screen.findByText("No articles.")).toBeInTheDocument();
  });

  it("says nothing is imported yet, with an icon", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ ...library, versions: [], default_version: null })),
    );
    show(() => <BrowsePage owner="acme" repo="payments" search={{}} />);
    const empty = await screen.findByText("Nothing imported yet");
    expect(empty.closest("div")?.parentElement?.querySelector("svg")).not.toBeNull();
  });

  it("waits in its final layout: a busy page with a heading that says it loads", async () => {
    show(() => <BrowseSkeleton />);
    expect(await screen.findByRole("main")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Loading the library");
  });
});
