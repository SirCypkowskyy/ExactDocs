import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AiRole } from "@/shared/lib/ai-queries";
import { HttpError } from "@/shared/lib/http";
import { AiPage } from "./index";
import {
  type Budget,
  budgetUsed,
  budgetWords,
  checkWords,
  explainAiError,
  ownBudgetNote,
  percent,
} from "./model/ai";

const SECRET = "sk-live-never-shown";

const provider = (name: string, extra: Record<string, unknown> = {}) => ({
  name,
  kind: "openai-compatible",
  origin: "api",
  read_only: false,
  base_url: "https://llm.example.com/v1",
  key: "sealed",
  header_names: ["X-Team"],
  proxy: null,
  request_timeout: 30,
  max_retries: 2,
  api_version: null,
  project: null,
  location: null,
  credentials_file: null,
  credentials: null,
  platform: null,
  auth: null,
  resource: null,
  roles: ["embedding", "llm"],
  unsupported: null,
  ...extra,
});

const PROVIDERS = [
  provider("corp"),
  provider("offline", {
    kind: "local",
    key: "none",
    base_url: null,
    roles: [],
    origin: "configuration",
  }),
];
const role = (r: Partial<AiRole> & Pick<AiRole, "role">): AiRole => ({
  model: null,
  source: null,
  profile_exists: false,
  thinking: null,
  own_thinking: null,
  thinking_configured: false,
  thinking_unsupported: null,
  ...r,
});
const ROLES: readonly AiRole[] = [
  role({ role: "embedding", model: "corp:e5", source: "instance", profile_exists: true }),
  role({ role: "reranker" }),
  role({
    role: "llm",
    model: "corp:gpt-4.1-mini",
    source: "instance",
    profile_exists: true,
    thinking: "low",
    own_thinking: "low",
    thinking_configured: true,
  }),
  role({
    role: "judge",
    model: "corp:gpt-4.1-mini",
    source: "llm",
    profile_exists: true,
    thinking: "low",
  }),
];
const EMBEDDING = {
  model: "corp:e5",
  spaces: [
    {
      id: 1,
      profile_kind: "openai-compatible",
      model: "e4",
      dimensions: 3,
      state: "active",
      current: false,
      created_at: "2026-11-01T10:00:00Z",
      activated_at: "2026-11-01T11:00:00Z",
      versions: 4,
      versions_embedded: 4,
      chunks: 200,
      chunks_embedded: 200,
    },
    {
      id: 2,
      profile_kind: "openai-compatible",
      model: "e5",
      dimensions: 3,
      state: "building",
      current: true,
      created_at: "2026-11-10T10:00:00Z",
      activated_at: null,
      versions: 4,
      versions_embedded: 1,
      chunks: 200,
      chunks_embedded: 50,
    },
  ],
};
const spent = (usd: number, tokens: number, local_tokens = 0) => ({
  input_tokens: tokens + local_tokens,
  output_tokens: 0,
  tokens,
  local_tokens,
  requests: 3,
  usd,
  unpriced_requests: 0,
});
const USAGE = {
  at: "2026-11-11T10:00:00Z",
  llm_searches_per_minute: 30,
  scopes: [
    {
      scope: "instance",
      id: "",
      day: spent(1.5, 3000),
      month: spent(4, 9000),
      budgets: [
        {
          window: "day",
          window_start: "2026-11-11",
          resets_at: "2026-11-12T00:00:00Z",
          usd_limit: 10,
          usd_left: 8.5,
          tokens_limit: null,
          tokens_left: null,
          reached: false,
        },
      ],
    },
    {
      scope: "embedding",
      id: "",
      day: spent(0, 0, 1200),
      month: spent(0, 0, 1200),
      budgets: [],
    },
    {
      scope: "library",
      id: "/acme/docs",
      day: spent(0.25, 500),
      month: spent(0.25, 500),
      budgets: [
        {
          window: "day",
          window_start: "2026-11-11",
          resets_at: "2026-11-12T00:00:00Z",
          usd_limit: 1,
          usd_left: 0.75,
          tokens_limit: null,
          tokens_left: null,
          reached: false,
          own_usd_limit: 2,
          own_tokens_limit: null,
        },
      ],
    },
    {
      scope: "library",
      id: "/acme/payments",
      day: spent(1, 2000),
      month: spent(1, 2000),
      budgets: [
        {
          window: "day",
          window_start: "2026-11-11",
          resets_at: "2026-11-12T00:00:00Z",
          usd_limit: 1,
          usd_left: 0,
          tokens_limit: null,
          tokens_left: null,
          reached: true,
        },
      ],
    },
  ],
};
const CHECKS = {
  checks: [
    {
      role: "embedding",
      profile: "corp",
      model: "e5",
      status: "ok",
      latency_ms: 41.7,
      served_model: "e5-v2",
      dimensions: 3,
      error: null,
    },
    {
      role: "llm",
      profile: "corp",
      model: "gpt-4.1-mini",
      status: "error",
      latency_ms: 12,
      served_model: null,
      dimensions: null,
      error: "401 Unauthorized",
    },
  ],
};

function serve(overrides: Record<string, { status: number; body: unknown }> = {}) {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  let roles = ROLES;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body });
      const path = url.replace(/^.*\/v1/, "");
      const over = overrides[path];
      if (over) return Response.json(over.body, { status: over.status });
      if (path === "/ai/providers") return Response.json({ providers: PROVIDERS });
      if (path === "/ai/roles") return Response.json({ roles });
      if (path === "/ai/roles/judge" && method === "PUT") {
        roles = roles.map((r) =>
          r.role === "judge" ? { ...r, own_thinking: body.thinking, thinking: body.thinking } : r,
        );
        return Response.json(roles.find((r) => r.role === "judge"));
      }
      if (path === "/ai/embedding") return Response.json(EMBEDDING);
      if (path === "/ai/usage") return Response.json(USAGE);
      if (path === "/ai/providers/corp/check" && method === "POST") return Response.json(CHECKS);
      return new Response("{}", { status: 404 });
    }),
  );
  return calls;
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AiPage />
    </QueryClientProvider>,
  );
}

const region = async (name: string) =>
  within(
    (await screen.findByRole("heading", { level: 2, name })).closest("section") as HTMLElement,
  );

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("instance AI page", () => {
  it("lists the providers and roles without ever a key, and checks one on demand", async () => {
    const calls = serve();
    renderPage();
    const providers = await region("Providers and roles");

    expect(await providers.findByRole("heading", { name: "corp" })).toBeInTheDocument();
    expect(providers.getByText(/Key stored, sealed/)).toBeInTheDocument();
    expect(providers.getByText(/offline/)).toBeInTheDocument();
    expect(providers.getByText("No instance role uses it.")).toBeInTheDocument();
    expect(providers.getByText(/the LLM's/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(SECRET);
    expect(calls.some((c) => c.method === "POST")).toBe(false); // a check costs a call: only on demand

    await userEvent.click(providers.getByRole("button", { name: "Check corp" }));

    const result = providers.getByRole("status", { name: "corp check" });
    expect(
      await within(result).findByText(/Answered in 42 ms by e5-v2, 3 dimensions/),
    ).toBeVisible();
    expect(within(result).getByText(/401 Unauthorized/)).toBeVisible();
  });

  it("sets the judge's thinking level, and shows a configured one as read-only", async () => {
    const calls = serve();
    renderPage();
    const providers = await region("Providers and roles");

    const llm = await providers.findByLabelText("LLM thinking");
    expect(llm).toBeDisabled();
    expect(llm).toHaveValue("low");
    expect(
      providers.getByText("Set in the configuration (EXACTDOCS_AI__LLM__THINKING)."),
    ).toBeInTheDocument();
    const judge = providers.getByLabelText("Judge thinking");
    expect(judge).toBeEnabled();
    expect(within(judge).getAllByRole("option")[0]).toHaveTextContent("The LLM's level (Low)");
    expect(providers.getByText(/Thinking tokens are billed as output/)).toBeInTheDocument();

    await userEvent.selectOptions(judge, "minimal");

    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")).toMatchObject({
        url: expect.stringMatching(/\/v1\/ai\/roles\/judge$/),
        body: { thinking: "minimal" },
      }),
    );
    await waitFor(() => expect(providers.getByLabelText("Judge thinking")).toHaveValue("minimal"));
  });

  it("says when a role's model cannot take its level", async () => {
    serve({
      "/ai/roles": {
        status: 200,
        body: {
          roles: ROLES.map((r) =>
            r.role === "llm" ? { ...r, thinking_unsupported: "openai serves it without one" } : r,
          ),
        },
      },
    });
    renderPage();
    const providers = await region("Providers and roles");

    expect(
      await providers.findByText(/Its model takes no thinking level, so its calls leave it out/),
    ).toBeInTheDocument();
  });

  it("shows embedding progress per space", async () => {
    serve();
    renderPage();
    const embedding = await region("Embedding");

    expect(await embedding.findByText("Space 2: e5")).toBeInTheDocument();
    expect(embedding.getByRole("progressbar", { name: "Space 2: e5 progress" })).toHaveAttribute(
      "aria-valuenow",
      "25",
    );
    expect(embedding.getByText(/25%: 50 of 200 chunks, 1 of 4 versions/)).toBeInTheDocument();
    expect(embedding.getByText("Building")).toBeInTheDocument();
    expect(embedding.getByText(/^Configured model ·/)).toBeInTheDocument();
    expect(embedding.getByText("Searched")).toBeInTheDocument();
    expect(embedding.getByText(/^Retired once the new one is done ·/)).toBeInTheDocument();
  });

  it("shows spend and the budget left per scope, and which budget is reached", async () => {
    serve();
    renderPage();
    const usage = await region("Usage and budgets");

    const instance = (await usage.findByRole("rowheader", { name: "The instance" })).closest(
      "tr",
    ) as HTMLElement;
    expect(within(instance).getByText("3,000 tokens · 3 calls")).toBeInTheDocument();
    expect(within(instance).getAllByText("$1.50").length).toBeGreaterThan(0);
    expect(within(instance).queryByText(/local/)).not.toBeInTheDocument();
    const embedding = usage
      .getByRole("rowheader", { name: "Embedding runs" })
      .closest("tr") as HTMLElement;
    // Local models' tokens are shown, apart: no token budget counts them (#284).
    expect(
      within(embedding).getAllByText(/0 tokens \(\+1,200 local, not budgeted\) · 3 calls/),
    ).toHaveLength(2);
    expect(within(instance).getByText("Today: $8.50 of $10.00 left")).toBeInTheDocument();
    const library = usage
      .getByRole("rowheader", { name: "Library /acme/payments" })
      .closest("tr") as HTMLElement;
    expect(
      within(library).getByText(/Today: \$0\.00 of \$1\.00 left · reached until/),
    ).toBeVisible();
    expect(usage.getByText(/LLM searches per minute per caller: 30/)).toBeInTheDocument();
    expect(within(library).queryByText(/instance limit is lower/)).not.toBeInTheDocument();
  });

  it("shows the instance limit that applies, with a note, when a library's own is higher", async () => {
    serve();
    renderPage();
    const usage = await region("Usage and budgets");

    const docs = (await usage.findByRole("rowheader", { name: "Library /acme/docs" })).closest(
      "tr",
    ) as HTMLElement;
    expect(within(docs).getByText("Today: $0.75 of $1.00 left")).toBeInTheDocument();
    expect(
      within(docs).getByText(
        "The instance limit is lower than the library's own budget ($2.00), so it applies.",
      ),
    ).toBeVisible();
  });

  it("says when a part cannot be read, and the rest still shows", async () => {
    serve({
      "/ai/embedding": {
        status: 503,
        body: { error: "vector_store_unavailable", detail: "no vector store", fields: [] },
      },
    });
    renderPage();

    const embedding = await region("Embedding");
    expect(await embedding.findByRole("alert")).toHaveTextContent("no vector store");
    expect(await screen.findByRole("rowheader", { name: "The instance" })).toBeInTheDocument();
  });
});

describe("ai model", () => {
  it("rounds progress down so only a finished space reads 100%", () => {
    expect(percent(199, 200)).toBe(99);
    expect(percent(200, 200)).toBe(100);
    expect(percent(0, 0)).toBe(100);
    expect(percent(1, 3)).toBe(33);
  });

  it("shows how much of a budget is used, and retries a part that failed", async () => {
    serve({ "/ai/usage": { status: 500, body: {} } });
    renderPage();
    const usage = await region("Usage and budgets");
    expect(await usage.findByRole("alert")).toHaveTextContent(/went wrong/);
    expect(usage.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("measures a budget by its tighter ceiling", () => {
    const day: Budget = {
      window: "day",
      window_start: "2026-11-11",
      resets_at: "2026-11-12T00:00:00Z",
      usd_limit: 10,
      usd_left: 2,
      tokens_limit: 1000,
      tokens_left: 900,
      reached: false,
    };
    expect(budgetUsed(day)).toBe(80);
    expect(budgetUsed({ ...day, reached: true })).toBe(100);
  });

  it("puts budgets and checks into words", () => {
    expect(
      budgetWords({
        window: "month",
        window_start: "2026-11-01",
        resets_at: "2026-12-01T00:00:00Z",
        usd_limit: null,
        usd_left: null,
        tokens_limit: 5000,
        tokens_left: 1200,
        reached: false,
      }),
    ).toBe("This month: 1,200 of 5,000 tokens left");
    const day: Budget = {
      window: "day",
      window_start: "2026-11-11",
      resets_at: "2026-11-12T00:00:00Z",
      usd_limit: null,
      usd_left: null,
      tokens_limit: 5000,
      tokens_left: 5000,
      reached: false,
    };
    expect(ownBudgetNote({ ...day, own_tokens_limit: 9000 })).toBe(
      "The instance limit is lower than the library's own budget (9,000 tokens), so it applies.",
    );
    expect(ownBudgetNote(day)).toBeNull();
    expect(checkWords({ ...CHECKS.checks[1], status: "error", error: null } as never)).toBe(
      "The call failed.",
    );
    expect(explainAiError(new HttpError(403, "/v1/ai/usage", {}))).toMatch(/Only admins/);
    expect(explainAiError(new TypeError("down"))).toMatch(/Can't reach/);
  });
});
