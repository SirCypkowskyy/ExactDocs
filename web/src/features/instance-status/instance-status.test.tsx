import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { aiUsageQueryOptions, healthQueryOptions, POLL_MS } from "./api/instance-status";
import { InstanceBanner } from "./index";
import { type AiUsage, noticesOf } from "./model/notices";

const NOW = Date.parse("2026-11-24T12:00:00Z");

interface State {
  reindex?: boolean;
  vector?: string | null;
  /** Reached instance budgets: `day` resets at midnight, `month` on the 1st. */
  reached?: ("day" | "month")[];
  /** The day window's start, to move to the next day. */
  day?: string;
}

const budget = (window: "day" | "month", reached: boolean, day = "2026-11-24") => ({
  window,
  window_start: window === "day" ? day : "2026-11-01",
  resets_at: window === "day" ? "2026-11-25T00:00:00Z" : "2026-12-01T00:00:00Z",
  usd_limit: 10,
  usd_left: reached ? 0 : 5,
  tokens_limit: null,
  tokens_left: null,
  reached,
  own_usd_limit: null,
  own_tokens_limit: null,
});

const spent = {
  input_tokens: 0,
  output_tokens: 0,
  tokens: 0,
  local_tokens: 0,
  requests: 0,
  usd: 0,
  unpriced_requests: 0,
};

function usageOf({ reached = [], day }: State): AiUsage {
  return {
    at: "2026-11-24T12:00:00Z",
    llm_searches_per_minute: null,
    scopes: [
      {
        scope: "instance",
        id: "",
        day: spent,
        month: spent,
        budgets: [
          budget("day", reached.includes("day"), day),
          budget("month", reached.includes("month")),
        ],
      },
      {
        // Another scope's reached budget is not the instance's.
        scope: "library",
        id: "/acme/payments",
        day: spent,
        month: spent,
        budgets: [budget("day", true)],
      },
    ],
  } as AiUsage;
}

function serve(state: State) {
  const fetchMock = vi.fn(async (input: string) => {
    const path = new URL(String(input), "http://x").pathname;
    if (path === "/api/health") {
      return Response.json({
        status: "ok",
        version: "1.0.0",
        database_reachable: true,
        schema_revision: "abc",
        search_index_format: 2,
        reindex_required: state.reindex ?? false,
        search_engine: "fts5",
        vector_store_missing: state.vector ?? null,
      });
    }
    if (path === "/api/v1/ai/usage") return Response.json(usageOf(state));
    return Response.json({ error: "not_found" }, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function OperatorShell() {
  return (
    <>
      <InstanceBanner operator />
      <Page />
    </>
  );
}

function ReaderShell() {
  return (
    <>
      <InstanceBanner operator={false} />
      <Page />
    </>
  );
}

function Page() {
  return (
    <main id="main">
      <h1 tabIndex={-1}>Libraries</h1>
    </main>
  );
}

function renderBanner(operator = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <TestRouter
          pages={{ "/": operator ? OperatorShell : ReaderShell, "/ai": () => <p>AI page</p> }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const region = () => screen.findByRole("status", { name: "Instance notices" });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  sessionStorage.clear();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  resetPreferences();
});

describe("which notices the instance raises", () => {
  it("raises nothing for a healthy instance", () => {
    expect(noticesOf({ status: "ok", reindex_required: false }, usageOf({}))).toEqual([]);
    expect(noticesOf(undefined, undefined)).toEqual([]);
  });

  it("raises nothing from a payload of another shape", () => {
    expect(noticesOf({ status: "ok" }, {} as AiUsage)).toEqual([]);
    expect(
      noticesOf({ status: "ok", vector_store_missing: 1 as never }, {
        scopes: [{ scope: "instance" }],
      } as unknown as AiUsage),
    ).toEqual([]);
  });

  it("puts the reindex first, then the vector store, then the budget", () => {
    const notices = noticesOf(
      { status: "ok", reindex_required: true, vector_store_missing: "vector" },
      usageOf({ reached: ["day"] }),
    );
    expect(notices.map((n) => n.kind)).toEqual(["reindex", "vector-store", "budget"]);
    expect(notices[0]?.dismissible).toBe(false);
  });

  it("names the month's budget when both the day's and the month's are reached", () => {
    const [notice] = noticesOf(undefined, usageOf({ reached: ["day", "month"] }));
    expect(notice).toMatchObject({
      kind: "budget",
      window: "month",
      condition: "month:2026-11-01",
    });
  });

  it("polls once a minute, and not while the tab is hidden", () => {
    for (const options of [healthQueryOptions(), aiUsageQueryOptions()]) {
      expect(options.refetchInterval).toBe(POLL_MS);
      expect(POLL_MS).toBe(60_000);
      expect(options.refetchIntervalInBackground).toBe(false);
    }
  });
});

describe("the instance banner", () => {
  it("shows operators nothing, and asks nothing, when they are not operators", async () => {
    const fetchMock = serve({ reindex: true, vector: "sqlite-vec", reached: ["day"] });
    renderBanner(false);
    expect(await screen.findByRole("heading", { name: "Libraries" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("stays empty on a healthy instance", async () => {
    const fetchMock = serve({});
    const { container } = renderBanner();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await screen.findByRole("heading", { name: "Libraries" });
    // The live region waits, empty and unnamed: no extra status on every page.
    expect(container.querySelector('[aria-live="polite"]')).toBeEmptyDOMElement();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("says the search index needs a rebuild, copies the command, and cannot be dismissed", async () => {
    serve({ reindex: true });
    const user = userEvent.setup();
    renderBanner();
    const status = await region();
    expect(
      await within(status).findByText(/The search index needs a rebuild after the upgrade/),
    ).toBeInTheDocument();
    expect(within(status).getByText("exactdocs reindex")).toBeInTheDocument();
    expect(within(status).queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();

    await user.click(within(status).getByRole("button", { name: "Copy the command" }));
    expect(await navigator.clipboard.readText()).toBe("exactdocs reindex");
    expect(within(status).getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("names the vector store's missing extension, and remembers a dismissal for the session", async () => {
    serve({ vector: "sqlite-vec" });
    const user = userEvent.setup();
    const { unmount } = renderBanner();
    const status = await region();
    expect(await within(status).findByText("sqlite-vec")).toBeInTheDocument();
    expect(within(status).getByText(/Hybrid search is off/)).toBeInTheDocument();
    expect(within(status).getByRole("link", { name: "Embedding status" })).toHaveAttribute(
      "href",
      "/ai#embedding",
    );

    await user.click(within(status).getByRole("button", { name: "Dismiss" }));
    expect(within(status).queryByText(/Hybrid search is off/)).not.toBeInTheDocument();
    // Nothing left: focus goes to the page's heading, not to <body>.
    expect(screen.getByRole("heading", { name: "Libraries" })).toHaveFocus();
    expect(JSON.parse(sessionStorage.getItem("exactdocs-dismissed-notices") ?? "[]")).toEqual([
      "vector-store:sqlite-vec",
    ]);

    // A reload in the same session keeps it away.
    unmount();
    serve({ reindex: true, vector: "sqlite-vec" });
    renderBanner();
    // The same answer that raises the reindex notice no longer raises the dismissed one.
    expect(await screen.findByText(/The search index needs a rebuild/)).toBeInTheDocument();
    expect(screen.queryByText(/Hybrid search is off/)).not.toBeInTheDocument();
  });

  it("shows a dismissed notice again when its condition changes", async () => {
    sessionStorage.setItem(
      "exactdocs-dismissed-notices",
      JSON.stringify(["vector-store:sqlite-vec", "budget:day:2026-11-23"]),
    );
    serve({ vector: "vector", reached: ["day"], day: "2026-11-24" });
    renderBanner();
    const status = await region();
    expect(await within(status).findByText("vector")).toBeInTheDocument();
    expect(
      await within(status).findByText(/The instance's AI budget for today is reached/),
    ).toBeInTheDocument();
  });

  it("says the instance's AI budget is reached, when it resets, and links to usage and budgets", async () => {
    serve({ reached: ["day"] });
    const user = userEvent.setup();
    renderBanner();
    const status = await region();
    expect(
      await within(status).findByText(
        "The instance's AI budget for today is reached. Searches skip their paid AI steps until it resets in 12 hours.",
        { exact: false },
      ),
    ).toBeInTheDocument();
    const link = within(status).getByRole("link", { name: "Usage and budgets" });
    expect(link).toHaveAttribute("href", "/ai#usage");
    await user.click(link);
    expect(await screen.findByText("AI page")).toBeInTheDocument();
  });

  it("moves focus to the next notice when one is dismissed", async () => {
    serve({ vector: "sqlite-vec", reached: ["month"] });
    const user = userEvent.setup();
    renderBanner();
    const status = await region();
    await within(status).findByText(/this month is reached/);
    const [first, second] = within(status).getAllByRole("button", { name: "Dismiss" });
    // Each Dismiss is told apart by the notice it closes.
    expect(first).toHaveAccessibleDescription(/Hybrid search is off/);
    expect(second).toHaveAccessibleDescription(/this month is reached/);
    await user.click(first as HTMLElement);
    expect(within(status).getByRole("button", { name: "Dismiss" })).toHaveFocus();
  });

  it("moves focus to the reindex notice's action, which has no Dismiss", async () => {
    serve({ reindex: true, vector: "sqlite-vec" });
    const user = userEvent.setup();
    renderBanner();
    const status = await region();
    await user.click(await within(status).findByRole("button", { name: "Dismiss" }));
    expect(within(status).getByRole("button", { name: "Copy the command" })).toHaveFocus();
  });

  it("still dismisses when the browser refuses storage", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    serve({ vector: "sqlite-vec" });
    const user = userEvent.setup();
    renderBanner();
    const status = await region();
    await within(status).findByText(/Hybrid search is off/);
    await user.click(within(status).getByRole("button", { name: "Dismiss" }));
    expect(within(status).queryByText(/Hybrid search is off/)).not.toBeInTheDocument();
  });

  it("speaks Polish", async () => {
    setPreferences({ language: "pl" });
    serve({ reindex: true, vector: "vector", reached: ["day"] });
    renderBanner();
    const status = await screen.findByRole("status", { name: "Komunikaty instancji" });
    expect(
      await within(status).findByText(/Po aktualizacji indeks wyszukiwania trzeba przebudować/),
    ).toBeInTheDocument();
    expect(within(status).getByRole("button", { name: "Kopiuj polecenie" })).toBeInTheDocument();
    expect(within(status).getByRole("link", { name: "Stan embeddingu" })).toBeInTheDocument();
    expect(within(status).getByText(/Wyszukiwanie hybrydowe jest wyłączone/)).toBeInTheDocument();
    expect(
      await within(status).findByText(
        "Dzienny budżet AI instancji został wyczerpany. Wyszukiwania pomijają płatne kroki AI, dopóki się nie odnowi (za 12 godzin).",
        { exact: false },
      ),
    ).toBeInTheDocument();
    expect(within(status).getByRole("link", { name: /Użycie i budżety/ })).toBeInTheDocument();
    expect(within(status).getAllByRole("button", { name: "Zamknij komunikat" })).toHaveLength(2);
  });
});
