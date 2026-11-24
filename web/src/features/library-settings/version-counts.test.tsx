import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { VersionsTable } from "./components/versions-table";

/* The versions table's sizes (#513): the Articles count and the Embedding meter. */

const SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";
const version = (ref: string, articles: number, chunks: number, embedded: number) => ({
  ref,
  kind: "tag",
  commit_sha: SHA,
  imported_at: "2026-11-01T10:00:00Z",
  is_default: ref === "v1.0.0",
  origin: "manual",
  articles,
  chunks,
  embedded_chunks: embedded,
});
const VERSIONS = [
  version("v1.0.0", 1234, 2000, 1234),
  version("v0.9.0", 5, 40, 40),
  version("v0.8.0", 2, 10, 0),
  version("v0.7.0", 0, 0, 0),
];

/** The library's retrieval settings, as far as the table reads them. */
const retrieval = (configured_roles: string[], ai_enabled = true) => ({
  status: 200,
  body: { library: "/acme/payments", ai_enabled, configured_roles },
});

/** `retrieval` undefined: the settings cannot be read (403), so the page cannot tell. */
function serve(versions: unknown[], settings?: { status: number; body: unknown }) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("/versions?")) {
        return Response.json({
          library: "/acme/payments",
          versions,
          next_cursor: null,
          total: versions.length,
        });
      }
      if (url.endsWith("/retrieval")) {
        const reply = settings ?? { status: 403, body: { error: "forbidden", detail: "" } };
        return Response.json(reply.body, { status: reply.status });
      }
      return new Response("{}", { status: 404 });
    }),
  );
  return calls;
}

function renderTable() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TestRouter
        pages={{
          "/libraries/$owner/$repo/settings": () => (
            <VersionsTable owner="acme" repo="payments" pinned={false} onRemove={() => {}} />
          ),
        }}
        start="/libraries/acme/payments/settings"
      />
    </QueryClientProvider>,
  );
}

const rowOf = async (ref: string) => {
  const table = await screen.findByRole("table");
  const row = (await within(table).findByText(ref)).closest("tr");
  if (!row) throw new Error(`no row ${ref}`);
  return within(row);
};

/** The phone layout: rows become cards. */
const onPhone = () =>
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query === "(max-width: 47.99rem)",
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  );

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  resetPreferences();
});

describe("the versions table's sizes", () => {
  it("counts each version's articles in a column the API does not sort", async () => {
    serve(VERSIONS, retrieval(["embedding"]));
    renderTable();
    const table = await screen.findByRole("table", { name: "Imported versions" });
    expect(within(table).getByRole("columnheader", { name: "Articles" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Embedding" })).toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: /Sort by Articles/ })).toBeNull();
    expect(within(table).queryByRole("button", { name: /Sort by Embedding/ })).toBeNull();
    expect((await rowOf("v1.0.0")).getByText("1,234")).toBeInTheDocument();
    expect((await rowOf("v0.9.0")).getByText("5")).toBeInTheDocument();
    // Both columns make room below `lg`.
    const articles = (await rowOf("v1.0.0")).getByText("1,234").closest("td");
    expect(articles).toHaveClass("max-lg:hidden");
  });

  it("meters the embedded chunks, named and explained as a count", async () => {
    serve(VERSIONS, retrieval(["embedding"]));
    renderTable();
    const row = await rowOf("v1.0.0");
    const meter = row.getByRole("meter", { name: "1,234 of 2,000 chunks embedded" });
    // 61.7 % rounds down: 100 % is said only of a version embedded in full.
    expect(meter).toHaveAttribute("aria-valuenow", "61");
    expect(row.getByText("61%")).toBeInTheDocument();
    expect(
      (await rowOf("v0.9.0")).getByRole("meter", { name: "40 of 40 chunks embedded" }),
    ).toHaveAttribute("aria-valuenow", "100");

    await userEvent.hover(meter);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("1,234 of 2,000 chunks embedded");
  });

  it("shows a version with no vectors yet as 0 of its chunks while the instance embeds", async () => {
    serve(VERSIONS, retrieval(["embedding"]));
    renderTable();
    const meter = (await rowOf("v0.8.0")).getByRole("meter", {
      name: "0 of 10 chunks embedded",
    });
    expect(meter).toHaveAttribute("aria-valuenow", "0");
  });

  it("says a version is not indexed when it has no chunks", async () => {
    serve(VERSIONS, retrieval(["embedding"]));
    renderTable();
    const row = await rowOf("v0.7.0");
    expect(row.queryByRole("meter")).toBeNull();
    expect(row.getByText("—")).toHaveAttribute("aria-hidden", "true");
    expect(row.getByText("Not indexed: this version has no chunks yet.")).toHaveClass("sr-only");
    // No articles either: the figure is muted.
    expect(row.getByText("0")).toHaveClass("text-muted-foreground");
  });

  it("says Not embedded when the instance has no embedding model", async () => {
    serve(VERSIONS, retrieval([]));
    renderTable();
    const row = await rowOf("v0.8.0");
    expect(await row.findByText("Not embedded")).toBeInTheDocument();
    expect(row.queryByRole("meter")).toBeNull();
    expect(
      row.getByText(". This instance has no embedding model configured.", { exact: false }),
    ).toHaveClass("sr-only");
    // A version that has vectors still shows them.
    expect((await rowOf("v1.0.0")).getByRole("meter")).toBeInTheDocument();
  });

  it("says Not embedded, and why, when AI is off for the library", async () => {
    serve(VERSIONS, retrieval([], false));
    renderTable();
    const row = await rowOf("v0.8.0");
    expect(await row.findByText("Not embedded")).toBeInTheDocument();
    expect(
      row.getByText(/AI is off for this library, so none of it is embedded\./),
    ).toBeInTheDocument();
  });

  it("keeps the 0 of N meter when the retrieval settings cannot be read", async () => {
    const calls = serve(VERSIONS);
    renderTable();
    const row = await rowOf("v0.8.0");
    expect(row.getByRole("meter", { name: "0 of 10 chunks embedded" })).toBeInTheDocument();
    expect(calls.some((u) => u.endsWith("/v1/libraries/acme/payments/retrieval"))).toBe(true);
    expect(screen.queryByText("Not embedded")).toBeNull();
  });

  it("puts both on a phone card in words", async () => {
    onPhone();
    serve(VERSIONS, retrieval(["embedding"]));
    renderTable();
    const cards = await screen.findByRole("list", { name: "Imported versions" });
    const [first, , , last] = within(cards).getAllByRole("listitem") as HTMLElement[];
    expect(first).toHaveTextContent("Articles: 1,234 articles");
    expect(first).toHaveTextContent("Embedding: 61% embedded");
    expect(
      within(first as HTMLElement).getByRole("meter", { name: "1,234 of 2,000 chunks embedded" }),
    ).toBeInTheDocument();
    expect(last).toHaveTextContent("Articles: 0 articles");
    expect(last).toHaveTextContent("Embedding: Not indexed");
  });
});

describe("the versions table's sizes in Polish", () => {
  it("groups, pluralises and names the meter in Polish", async () => {
    setPreferences({ language: "pl" });
    serve(
      [
        version("v1.0.0", 12345, 20000, 1234),
        version("v0.9.0", 1, 1, 0),
        version("v0.8.0", 2, 2, 2),
        version("v0.7.0", 0, 0, 0),
      ],
      retrieval(["embedding"]),
    );
    renderTable();
    const table = await screen.findByRole("table", { name: "Zaimportowane wersje" });
    expect(within(table).getByRole("columnheader", { name: "Artykuły" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Embeddingi" })).toBeInTheDocument();
    const first = await rowOf("v1.0.0");
    expect(first.getByText("12 345")).toBeInTheDocument();
    expect(
      first.getByRole("meter", { name: "Embeddingi: 1234 z 20\u00a0000 fragmentów" }),
    ).toHaveAttribute("aria-valuenow", "6");
    expect(
      (await rowOf("v0.9.0")).getByRole("meter", { name: "Embeddingi: 0 z 1 fragmentu" }),
    ).toBeInTheDocument();
    expect(
      (await rowOf("v0.7.0")).getByText("Nie zaindeksowano: ta wersja nie ma jeszcze fragmentów."),
    ).toBeInTheDocument();
  });

  it("says the articles with the Polish plural on a phone card", async () => {
    setPreferences({ language: "pl" });
    onPhone();
    serve([version("v3", 1, 1, 1), version("v2", 2, 2, 0), version("v1", 5, 0, 0)], retrieval([]));
    renderTable();
    const cards = await screen.findByRole("list", { name: "Zaimportowane wersje" });
    const [one, two, five] = within(cards).getAllByRole("listitem") as HTMLElement[];
    expect(one).toHaveTextContent("Artykuły: 1 artykuł");
    expect(one).toHaveTextContent("Embeddingi: embeddingi: 100%");
    expect(two).toHaveTextContent("Artykuły: 2 artykuły");
    expect(two).toHaveTextContent("Embeddingi: Bez embeddingów");
    expect(five).toHaveTextContent("Artykuły: 5 artykułów");
    expect(five).toHaveTextContent("Embeddingi: Nie zaindeksowano");
  });
});
