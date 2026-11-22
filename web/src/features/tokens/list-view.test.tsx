import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TokensSection } from "./index";
import { parseTokensView, type TokensView, tokensParams } from "./model/list-view";

const token = (name: string) => ({
  id: name,
  name,
  prefix: "exd_abcd",
  created_at: "2026-11-13T10:00:00Z",
  expires_at: null,
  last_used_at: null,
  library_ids: null,
});

/** `q=ci` matches two tokens, `q=zzz` none; anything else lists all three. */
function serve() {
  const fetchMock = vi.fn(async (url: string) => {
    const all = [token("laptop"), token("ci-main"), token("ci-nightly")];
    const q = new URL(url, "http://x").searchParams.get("q") ?? "";
    const tokens = all.filter((t) => t.name.includes(q));
    return Response.json({ tokens, next_cursor: null, total: tokens.length });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const urls = (fetchMock: ReturnType<typeof serve>) =>
  fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/v1/tokens?"));

function Harness({ start, seen }: { start: TokensView; seen: TokensView[] }) {
  const [view, setView] = useState(start);
  return (
    <TokensSection
      view={view}
      onView={(next) => {
        seen.push(next);
        setView(next);
      }}
    />
  );
}

function renderSection(start: TokensView = {}) {
  const seen: TokensView[] = [];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness start={start} seen={seen} />
    </QueryClientProvider>,
  );
  return seen;
}

describe("the token list view", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps only what the API knows from a hand-edited URL", () => {
    expect(parseTokensView({ q: " ci ", sort: "-last_used_at", x: 1 })).toEqual({
      q: "ci",
      sort: "-last_used_at",
    });
    expect(parseTokensView({ sort: "token_hash" })).toEqual({ q: undefined, sort: undefined });
    expect(tokensParams({ q: "ci", sort: "name" }, "c1")).toBe("limit=50&q=ci&sort=name&cursor=c1");
  });

  it("searches and sorts on the server, and counts what matches", async () => {
    const fetchMock = serve();
    const seen = renderSection();
    expect(await screen.findByText("Showing 3 of 3")).toBeInTheDocument();

    await userEvent.type(screen.getByRole("searchbox", { name: "Find a token" }), "ci");
    expect(await screen.findByText("Showing 2 of 2")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Sort by" }), "-name");

    expect(seen.at(-1)).toEqual({ q: "ci", sort: "-name" });
    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/tokens?limit=50&q=ci&sort=-name"),
    );
  });

  it("tells a search that matches nothing from having no tokens at all", async () => {
    serve();
    const seen = renderSection({ q: "zzz" });

    expect(await screen.findByText("No tokens match")).toBeInTheDocument();
    expect(screen.queryByText(/no tokens yet/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(seen.at(-1)).toEqual({ sort: undefined });
  });
});
