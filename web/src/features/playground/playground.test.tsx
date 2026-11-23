import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { PlaygroundPage } from "./index";
import {
  fallbackSentence,
  librariesRanked,
  rankLabels,
  searchableLibraries,
} from "./model/playground";

const SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";

const summary = (id: string, default_version: string | null = "v1") => ({
  id,
  title: id,
  description: "",
  default_version,
});

const hit = (library: string, over: Record<string, unknown> = {}) => ({
  chunk_id: `c-${library}`,
  article_path: "docs/retry.md",
  heading_path: ["Guide", "Retry policy"],
  anchor: "retry-policy",
  position: 0,
  total: 1,
  prev_chunk_id: null,
  next_chunk_id: null,
  commit_sha: SHA,
  source_url: null,
  tags: [],
  score: 0.5,
  snippet: "RetryPolicy decides how often a failed call runs again.",
  highlights: [],
  justification: null,
  explored_path: [],
  library,
  version: "v1",
  bm25_rank: null,
  vector_rank: null,
  ...over,
});

const result = (mode: string, hits: unknown[], over: Record<string, unknown> = {}) => ({
  notice: "",
  retrieval_mode: mode,
  reranked: false,
  coverage: { candidates: hits.length, reranked: 0, complete: true },
  fallback_reason: null,
  libraries_searched: 2,
  libraries_omitted: 0,
  libraries_without_vectors: [],
  libraries: [],
  results: hits,
  ...over,
});

interface Agent {
  availability: Record<string, unknown>;
  stream: () => Response;
}

function serve(answer: (url: URL) => Response, agent?: Agent) {
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(input, "http://localhost");
    if (url.pathname.endsWith("/v1/libraries")) {
      return Response.json({
        libraries: [summary("/acme/payments"), summary("/acme/billing"), summary("/x/empty", null)],
        next_cursor: null,
      });
    }
    if (url.pathname.endsWith("/v1/search")) return answer(url);
    if (agent && url.pathname.endsWith("/v1/answer")) return Response.json(agent.availability);
    if (agent && url.pathname.endsWith("/v1/answer/stream")) return agent.stream();
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <Suspense fallback="loading">
        <TestRouter
          pages={{ "/": PlaygroundPage, "/libraries/$owner/$repo": () => <p>Reader</p> }}
        />
      </Suspense>
    </QueryClientProvider>,
  );
}

const searches = (fetchMock: ReturnType<typeof serve>) =>
  fetchMock.mock.calls
    .map(([input]) => new URL(input, "http://localhost"))
    .filter((u) => u.pathname.endsWith("/v1/search"));

describe("search playground", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("searches the chosen libraries in the chosen mode and shows each result's ranks", async () => {
    const fetchMock = serve((url) =>
      Response.json(
        result(url.searchParams.get("mode") ?? "bm25", [
          hit("/acme/payments", { bm25_rank: 1, vector_rank: 3 }),
          hit("/acme/billing", { vector_rank: 1 }),
        ]),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByLabelText("/acme/payments"));
    await user.click(screen.getByLabelText("/acme/billing"));
    expect(screen.queryByLabelText("/x/empty")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Query"), "retry failed calls");
    await user.click(screen.getByRole("button", { name: "Search" }));

    const list = await screen.findByRole("list", { name: "Hybrid (BM25 + vectors) results" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0] as HTMLElement).getByText("BM25 #1")).toBeInTheDocument();
    expect(within(items[0] as HTMLElement).getByText("vector #3")).toBeInTheDocument();
    expect(within(items[1] as HTMLElement).getByText("vector #1")).toBeInTheDocument();
    expect(within(items[0] as HTMLElement).getByRole("link")).toHaveAttribute(
      "href",
      "/libraries/acme/payments?version=v1&path=docs%2Fretry.md#retry-policy",
    );
    const [sent] = searches(fetchMock);
    expect(sent?.searchParams.get("mode")).toBe("hybrid");
    expect(sent?.searchParams.get("library")).toBe("/acme/payments,/acme/billing");
    expect(sent?.searchParams.get("q")).toBe("retry failed calls");
  });

  it("counts only the chosen libraries in the summary, not every library counted (#479)", async () => {
    // The API counts every readable library's matches (`libraries_searched: 2`) even when one
    // library is chosen; the results come from the chosen one only.
    const fetchMock = serve((url) =>
      Response.json(
        result(url.searchParams.get("mode") ?? "bm25", [
          hit("/acme/payments", { bm25_rank: 1 }),
          hit("/acme/payments", { chunk_id: "c-2", bm25_rank: 2 }),
        ]),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByLabelText("/acme/payments"));
    await user.type(screen.getByLabelText("Query"), "how do I retry failed calls");
    await user.click(screen.getByLabelText("Compare two modes side by side"));
    await user.click(screen.getByRole("button", { name: "Search" }));

    const summaries = await screen.findAllByText(/2 results from/);
    expect(summaries).toHaveLength(2);
    for (const line of summaries) expect(line).toHaveTextContent(/2 results from 1 library$/);
    const sent = searches(fetchMock);
    expect(sent.map((u) => u.searchParams.get("library"))).toEqual([
      "/acme/payments",
      "/acme/payments",
    ]);
  });

  it("counts every library searched when none is chosen", async () => {
    serve(() => Response.json(result("hybrid", [hit("/acme/payments")])));
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText("Query"), "retry");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText(/1 result from/)).toHaveTextContent(
      /1 result from 2 libraries$/,
    );
  });

  it("compares two modes side by side for the same query, over all libraries", async () => {
    const fetchMock = serve((url) =>
      Response.json(result(url.searchParams.get("mode") ?? "bm25", [hit("/acme/payments")])),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText("Query"), "retry");
    await user.click(screen.getByLabelText("Compare two modes side by side"));
    await user.selectOptions(screen.getByLabelText("Mode"), "vector");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(
      await screen.findByRole("list", { name: "Vector (embeddings) results" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("list", { name: "BM25 (keywords) results" }),
    ).toBeInTheDocument();
    const sent = searches(fetchMock);
    expect(sent.map((u) => u.searchParams.get("mode")).sort()).toEqual(["bm25", "vector"]);
    expect(sent.every((u) => !u.searchParams.has("library"))).toBe(true);
  });

  it("says why a mode is unavailable, and why BM25 answered instead", async () => {
    serve((url) =>
      url.searchParams.get("mode") === "vector"
        ? Response.json(
            {
              error: "mode_unavailable",
              detail: "the mode 'vector' needs the embedding role, not configured",
              fields: [],
              close_matches: [],
              library_id: null,
            },
            { status: 422 },
          )
        : Response.json(
            result("bm25", [hit("/acme/payments", { bm25_rank: 1 })], {
              fallback_reason: "embedding_in_progress",
            }),
          ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText("Query"), "retry");
    await user.click(screen.getByLabelText("Compare two modes side by side"));
    await user.selectOptions(screen.getByLabelText("Mode"), "vector");
    await user.selectOptions(screen.getByLabelText("Compare with"), "hybrid");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Unavailable: .*embedding role/);
    expect(await screen.findByText(/BM25 answered instead/)).toBeInTheDocument();
  });
});

const events = (...parts: [string, unknown][]) =>
  new Response(
    new ReadableStream({
      start(controller) {
        const encoder = new TextEncoder();
        for (const [name, data] of parts) {
          controller.enqueue(
            encoder.encode(`event: ${name}
data: ${JSON.stringify(data)}

`),
          );
        }
        controller.close();
      },
    }),
    { headers: { "Content-Type": "text/event-stream" } },
  );

const usage = {
  requests: 2,
  input_tokens: 1200,
  output_tokens: 80,
  tool_calls: 3,
  max_tool_calls: 20,
  cost_usd: 0.0123,
};

const source = {
  library: "/acme/payments",
  version: "v1",
  commit_sha: SHA,
  chunk_id: "c-1",
  article_path: "docs/retry.md",
  heading_path: ["Guide", "Retry policy"],
  anchor: "retry-policy",
  source_url: null,
  quote: "RetryPolicy decides how often a failed call runs again.",
  reason: "It defines the policy.",
};

const answered = (over: Record<string, unknown> = {}) => ({
  notice: "",
  answer: "Use RetryPolicy.",
  sources: [source],
  libraries: [],
  libraries_without_ai: [],
  libraries_omitted: 0,
  fallback_reason: null,
  usage,
  ...over,
});

describe("agent answer in the playground", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the agent disabled with the reason when no llm role is configured", async () => {
    serve(() => Response.json(result("bm25", [])), {
      availability: { available: false, reason: "no llm role is configured", max_tool_calls: 20 },
      stream: () => events(),
    });
    renderPage();

    const option = await screen.findByRole("option", { name: "Agent answer (unavailable)" });
    expect(option).toBeDisabled();
    expect(screen.getByText(/no llm role is configured/)).toBeInTheDocument();
  });

  it("asks the agent over the chosen libraries and shows progress, answer, sources and spend", async () => {
    const fetchMock = serve(() => Response.json(result("bm25", [])), {
      availability: { available: true, reason: null, max_tool_calls: 20 },
      stream: () =>
        events(
          ["progress", { tool_calls: 1, max_tool_calls: 20 }],
          ["progress", { tool_calls: 3, max_tool_calls: 20 }],
          ["answer", answered()],
        ),
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByLabelText("/acme/payments"));
    await user.type(screen.getByLabelText("Query"), "retry failed calls");
    await user.selectOptions(
      screen.getByLabelText("Mode"),
      await screen.findByRole("option", { name: "Agent answer (an LLM reads and answers)" }),
    );
    await user.click(screen.getByRole("button", { name: "Ask the agent" }));

    expect(await screen.findByText("Use RetryPolicy.")).toBeInTheDocument();
    expect(screen.getByText(/3 of 20 tool calls/)).toBeInTheDocument();
    expect(screen.getByText("1,200 in / 80 out tokens", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/\$0\.0123/)).toBeInTheDocument();
    const sources = screen.getByRole("list", { name: "Sources" });
    expect(within(sources).getByRole("link")).toHaveAttribute(
      "href",
      "/libraries/acme/payments?version=v1&path=docs%2Fretry.md#retry-policy",
    );
    expect(within(sources).getByText(/RetryPolicy decides/)).toBeInTheDocument();
    const calls = fetchMock.mock.calls as unknown as [string, RequestInit | undefined][];
    const call = calls.find(([input]) => input.endsWith("/v1/answer/stream"));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      question: "retry failed calls",
      libraries: ["/acme/payments"],
    });
  });

  it("says why the agent did not answer, with what it read", async () => {
    serve(() => Response.json(result("bm25", [])), {
      availability: { available: true, reason: null, max_tool_calls: 20 },
      stream: () =>
        events(["answer", answered({ answer: "", fallback_reason: "agent_limit_reached" })]),
    });
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText("Query"), "retry");
    await user.selectOptions(
      screen.getByLabelText("Mode"),
      await screen.findByRole("option", { name: "Agent answer (an LLM reads and answers)" }),
    );
    await user.click(screen.getByRole("button", { name: "Ask the agent" }));

    expect(await screen.findByText(/No answer: .*tool calls or time/)).toBeInTheDocument();
    expect(screen.getByText("Read before it stopped")).toBeInTheDocument();
  });

  it("shows an error event", async () => {
    serve(() => Response.json(result("bm25", [])), {
      availability: { available: true, reason: null, max_tool_calls: 20 },
      stream: () => events(["error", { error: "version_not_indexed", detail: "no such library" }]),
    });
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText("Query"), "retry");
    await user.selectOptions(
      screen.getByLabelText("Mode"),
      await screen.findByRole("option", { name: "Agent answer (an LLM reads and answers)" }),
    );
    await user.click(screen.getByRole("button", { name: "Ask the agent" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("no such library");
  });
});

describe("playground model", () => {
  it("names the ranks a result holds", () => {
    expect(rankLabels({ bm25_rank: 2, vector_rank: null })).toEqual(["BM25 #2"]);
    expect(rankLabels({ bm25_rank: null, vector_rank: 1 })).toEqual(["vector #1"]);
    expect(rankLabels({ bm25_rank: null, vector_rank: null })).toEqual([]);
  });

  it("offers only libraries with a default version, by ID", () => {
    const libraries = [summary("/b/b"), summary("/a/a"), summary("/c/c", null)];
    expect(searchableLibraries(libraries as never)).toEqual(["/a/a", "/b/b"]);
  });

  it("counts the chosen libraries as ranked, or every one searched when none is chosen", () => {
    const counted = { libraries_searched: 2 };
    expect(librariesRanked(["/acme/payments"], counted)).toBe(1);
    expect(librariesRanked(["/acme/payments", "/ACME/Payments"], counted)).toBe(1);
    expect(librariesRanked([], counted)).toBe(2);
  });

  it("explains a fallback in a sentence", () => {
    expect(fallbackSentence("embedding_unavailable")).toMatch(/embedding model failed/);
  });
});
