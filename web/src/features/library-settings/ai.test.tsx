import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { TestRouter } from "@/shared/lib/test-router";
import { LibrarySettingsPage } from "./index";
import {
  bodyOf,
  type LibraryRetrieval,
  modeOptions,
  modeSource,
  pipelineSteps,
  profileOptions,
  retrievalDraftOf,
  rolesInUse,
  validateRetrieval,
} from "./model/retrieval";
import { explainRetrievalSave } from "./model/settings";

const library = {
  id: "/acme/payments",
  title: "Payments",
  description: "",
  source_url: "https://github.com/acme/payments",
  host: "github",
  default_branch: "main",
  settings: { include_paths: [], exclude_paths: [], tag_rules: [], chunking: {} },
  default_version: "v1",
  versions: [],
};

const NO_BUDGETS = { daily_usd: null, monthly_usd: null, daily_tokens: null, monthly_tokens: null };

/** An instance with an embedding model only: hybrid is the best mode. */
const HYBRID: LibraryRetrieval = {
  library: "/acme/payments",
  mode: null,
  instance_mode: null,
  effective_mode: "hybrid",
  fallback_reason: null,
  available_modes: ["bm25", "hybrid"],
  configured_roles: ["embedding"],
  ai_enabled: true,
  llm: null,
  judge: null,
  reranker: null,
  rerank_top_n: null,
  effective_rerank_top_n: 32,
  budgets: NO_BUDGETS,
  budget_ceilings: { ...NO_BUDGETS, daily_usd: 2 },
  repo_guidance: "off",
};

/** What the server answers once AI is off: BM25 only, no role. */
const OFF: LibraryRetrieval = {
  ...HYBRID,
  ai_enabled: false,
  effective_mode: "bm25",
  available_modes: ["bm25"],
  configured_roles: [],
};

const provider = (name: string, unsupported: string | null = null) => ({
  name,
  kind: "openai-compatible",
  origin: "configuration",
  read_only: true,
  base_url: "https://llm.example.com/v1",
  key: "environment",
  header_names: [],
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
  roles: name === "corp" ? ["embedding"] : [],
  unsupported,
});
const PROVIDERS = [provider("corp"), provider("vertex", "needs the [ai] extra")];
const ROLES = [
  {
    role: "embedding",
    model: "corp:text-embedding-3-small",
    source: "instance",
    profile_exists: true,
  },
  { role: "reranker", model: null, source: null, profile_exists: false },
  { role: "llm", model: "corp:gpt-4.1-mini", source: "instance", profile_exists: true },
  { role: "judge", model: null, source: null, profile_exists: false },
];

type Reply = { status: number; body: unknown };

function serve(
  initial: LibraryRetrieval,
  put?: (body: Record<string, unknown>) => Reply,
  profiles: () => Promise<Response> = async () => Response.json({ providers: PROVIDERS }),
) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  let stored = initial;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body });
      if (url.endsWith("/v1/ai/providers")) return profiles();
      if (url.endsWith("/v1/ai/roles")) return Response.json({ roles: ROLES });
      if (url.endsWith("/retrieval") && method === "PUT") {
        const reply = put?.(body) ?? { status: 200, body: { ...stored, ...body } };
        if (reply.status === 200) stored = reply.body as LibraryRetrieval;
        return Response.json(reply.body, { status: reply.status });
      }
      if (url.endsWith("/retrieval")) return Response.json(stored);
      return new Response("{}", { status: 404 });
    }),
  );
  return calls;
}

const jobs = { Import: () => null, Line: () => null, Preview: () => null };

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TestRouter
        pages={{
          "/": () => <p>Libraries home</p>,
          "/libraries/$owner/$repo": () => <p>Browse</p>,
          "/libraries/$owner/$repo/settings": () => (
            <LibrarySettingsPage
              owner="acme"
              repo="payments"
              library={library as never}
              jobs={jobs as never}
            />
          ),
        }}
        start="/libraries/acme/payments/settings"
      />
    </QueryClientProvider>,
  );
}

const section = async () =>
  within(
    (await screen.findByRole("heading", { name: "Retrieval and AI" })).closest(
      "section",
    ) as HTMLElement,
  );

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("library AI settings", () => {
  it("shows the effective pipeline and offers only the modes that can run", async () => {
    serve(HYBRID);
    renderPage();
    const ai = await section();

    expect(await ai.findByTestId("effective-mode")).toHaveTextContent("Hybrid");
    expect(ai.getByText("The best mode the instance has configured.")).toBeInTheDocument();
    expect(ai.getByText("Vector search with the embedding model")).toBeInTheDocument();
    expect(ai.getByText("corp:text-embedding-3-small")).toBeInTheDocument();
    const mode = ai.getByLabelText("Retrieval mode");
    const options = within(mode)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(["The best mode available", "BM25", "Hybrid"]);
  });

  it("switches a library's AI off and then says nothing is sent", async () => {
    const calls = serve(HYBRID, () => ({ status: 200, body: OFF }));
    renderPage();
    const ai = await section();
    await ai.findByTestId("effective-mode");

    await userEvent.click(ai.getByLabelText("Use AI providers for this library"));
    const mode = ai.getByLabelText("Retrieval mode");
    expect(
      within(mode)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["The best mode available", "BM25"]);
    await userEvent.click(ai.getByRole("button", { name: "Save AI settings" }));

    await waitFor(() => expect(ai.getByTestId("effective-mode")).toHaveTextContent("BM25"));
    expect(ai.getByText("No content of this library is sent to any AI provider.")).toBeVisible();
    expect(await ai.findByText("Saved.")).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body).toMatchObject({ ai_enabled: false, mode: null });
  });

  it("overrides a role with a usable profile only, and asks for its model", async () => {
    const calls = serve(HYBRID);
    renderPage();
    const ai = await section();
    await ai.findByTestId("effective-mode");

    const profile = ai.getByLabelText("LLM profile");
    await waitFor(() =>
      expect(
        within(profile)
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["The instance's", "corp"]),
    );
    await userEvent.selectOptions(profile, "corp");
    await userEvent.click(ai.getByRole("button", { name: "Save AI settings" }));
    expect(ai.getByText("Name the model to use.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);

    await userEvent.type(ai.getByLabelText("LLM model"), "gpt-4.1");
    await userEvent.click(ai.getByRole("button", { name: "Save AI settings" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ llm: "corp:gpt-4.1" });
  });

  it("keeps a budget within the instance's and shows the server's refusal", async () => {
    const calls = serve(HYBRID, () => ({
      status: 422,
      body: {
        error: "budget_above_instance",
        detail: "the library's monthly_usd may be at most the instance's 5 USD",
        fields: [],
      },
    }));
    renderPage();
    const ai = await section();
    await ai.findByTestId("effective-mode");
    expect(ai.getByText("At most 2 USD, the instance's limit.")).toBeInTheDocument();

    await userEvent.type(ai.getByLabelText("US dollars per day"), "3");
    await userEvent.click(ai.getByRole("button", { name: "Save AI settings" }));
    expect(ai.getByText("The instance allows a library at most 2 USD.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);

    await userEvent.clear(ai.getByLabelText("US dollars per day"));
    await userEvent.type(ai.getByLabelText("US dollars per month"), "50");
    await userEvent.click(ai.getByRole("button", { name: "Save AI settings" }));

    expect(await ai.findByText(/monthly_usd may be at most/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
      budgets: { daily_usd: null, monthly_usd: 50 },
    });
  });
});

describe("repository guidance", () => {
  it("lets the owner take the instruction files as untrusted notes, and says what each does", async () => {
    const calls = serve(HYBRID);
    renderPage();
    const ai = await section();
    await ai.findByTestId("effective-mode");

    const guidance = ai.getByLabelText("Repository guidance (AGENTS.md / CLAUDE.md)");
    expect(
      within(guidance)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Off", "Untrusted notes", "Trusted instructions"]);
    expect(ai.getByText(/Imports keep no instruction file/)).toBeInTheDocument();
    await userEvent.selectOptions(guidance, "notes");
    expect(ai.getByText(/never as instructions/)).toBeInTheDocument();
    await userEvent.click(ai.getByRole("button", { name: "Save AI settings" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ repo_guidance: "notes" });
  });

  it("disables the choice while AI is off", async () => {
    serve(OFF);
    renderPage();
    const ai = await section();
    await ai.findByTestId("effective-mode");

    expect(ai.getByLabelText("Repository guidance (AGENTS.md / CLAUDE.md)")).toBeDisabled();
  });
});

describe("profiles while they load or fail", () => {
  const stored = { ...HYBRID, llm: "corp:gpt-4.1" };

  it("offers the stored override as it is and disables the choice while profiles load", async () => {
    let release: (r: Response) => void = () => {};
    serve(stored, undefined, () => new Promise((resolve) => (release = resolve)));
    renderPage();
    const ai = await section();
    await ai.findByTestId("effective-mode");

    const profile = ai.getByLabelText("LLM profile");
    expect(profile).toBeDisabled();
    expect(ai.getByText("Loading the profiles…")).toBeInTheDocument();
    expect(
      within(profile)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["The instance's", "corp"]);

    release(Response.json({ providers: PROVIDERS }));
    await waitFor(() => expect(ai.getByLabelText("LLM profile")).toBeEnabled());
    expect(ai.queryByText("Loading the profiles…")).not.toBeInTheDocument();
  });

  it("says when the profiles cannot be read, without calling the stored one missing", async () => {
    serve(stored, undefined, async () =>
      Response.json({ error: "internal", detail: "x", fields: [] }, { status: 500 }),
    );
    renderPage();
    const ai = await section();

    expect(await ai.findByText(/The AI profiles could not be read/)).toBeInTheDocument();
    const profile = ai.getByLabelText("LLM profile");
    expect(profile).toBeDisabled();
    expect(within(profile).queryByText(/not available/)).not.toBeInTheDocument();
  });

  it("keeps a stored budget above a lowered instance limit, warns, and saves other changes", async () => {
    const lowered = {
      ...HYBRID,
      budgets: { ...NO_BUDGETS, daily_usd: 4 },
      budget_ceilings: { ...NO_BUDGETS, daily_usd: 2 },
    };
    const calls = serve(lowered);
    renderPage();
    const ai = await section();
    await ai.findByTestId("effective-mode");

    expect(
      ai.getByText(/Above the instance's limit of 2 USD, which applies instead/),
    ).toBeVisible();
    await userEvent.type(ai.getByLabelText("Candidates to rerank"), "8");
    await userEvent.click(ai.getByRole("button", { name: "Save AI settings" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
      rerank_top_n: 8,
      budgets: { daily_usd: 4 },
    });
  });
});

describe("retrieval model", () => {
  it("lists only the roles the effective pipeline calls, the library's model first", () => {
    const r = { ...HYBRID, configured_roles: ["embedding", "reranker", "llm", "judge"] as const };
    expect(
      rolesInUse({ ...r, effective_mode: "hybrid_hyde", llm: "own:o3" }, ROLES as never),
    ).toEqual([
      { role: "embedding", model: "corp:text-embedding-3-small", from: "instance" },
      { role: "reranker", model: undefined, from: "instance" },
      { role: "llm", model: "own:o3", from: "library" },
    ]);
    // BM25 calls no model: an instance LLM is configured but not listed.
    expect(
      rolesInUse({ ...r, effective_mode: "bm25", configured_roles: ["llm"] }, ROLES as never),
    ).toEqual([]);
    expect(rolesInUse(r as never, undefined)[0]?.model).toBeUndefined();
  });

  it("lists the reranker step only when one is configured", () => {
    expect(pipelineSteps(HYBRID)).not.toContain("The reranker reorders the best 32");
    expect(pipelineSteps({ ...HYBRID, configured_roles: ["embedding", "reranker"] }).at(-1)).toBe(
      "The reranker reorders the best 32",
    );
  });

  it("shows the agentic pipeline's steps and its single llm role", () => {
    const r = { ...HYBRID, effective_mode: "agentic" as const, configured_roles: ["llm" as const] };
    expect(pipelineSteps(r)).toEqual([
      "An LLM agent browses this version in a sandbox: outlines, articles, chunks and keyword search",
      "Its picks are checked against this version, each with why it was picked",
    ]);
    expect(rolesInUse(r, ROLES as never).map((x) => x.role)).toEqual(["llm"]);
  });

  it("says in words why the agent's run ended", () => {
    for (const [reason, words] of [
      ["agent_limit_reached", "The agent ran past its limits, so a cheaper mode answered."],
      ["agent_failed", "The agent could not finish, so a cheaper mode answered."],
      [
        "agent_loop_detected",
        "The agent kept repeating the same call, so a cheaper mode answered.",
      ],
    ] as const) {
      expect(modeSource({ ...HYBRID, fallback_reason: reason })).toBe(words);
    }
  });

  it("names the repository's instruction files in the agentic pipeline when guidance is on", () => {
    const r = { ...HYBRID, effective_mode: "agentic" as const, configured_roles: ["llm" as const] };
    expect(pipelineSteps({ ...r, repo_guidance: "notes" })[1]).toBe(
      "A folder's AGENTS.md / CLAUDE.md reaches it as an untrusted note when it opens the folder",
    );
    expect(pipelineSteps({ ...r, repo_guidance: "trusted" })[1]).toMatch(
      /root AGENTS.md \/ CLAUDE.md is part of its instructions/,
    );
    expect(pipelineSteps({ ...HYBRID, repo_guidance: "notes" })).toEqual(pipelineSteps(HYBRID));
  });

  it("keeps a stored mode that can't run visible but not choosable", () => {
    const r = { ...HYBRID, mode: "agentic" as const, fallback_reason: "mode_unavailable" as const };
    expect(modeOptions(r, retrievalDraftOf(r)).at(-1)).toEqual({
      value: "agentic",
      label: "Agentic (can't run now)",
      disabled: true,
    });
    expect(profileOptions(PROVIDERS as never, "gone")).toEqual([
      { value: "corp", note: "" },
      { value: "gone", note: " (not available)" },
    ]);
  });

  it("sends every setting back, and checks what needs no server", () => {
    const stored = {
      ...HYBRID,
      mode: "hybrid" as const,
      reranker: "tei:bge:v2",
      rerank_top_n: 8,
      budgets: { ...NO_BUDGETS, monthly_tokens: 1000 },
    };
    expect(bodyOf(retrievalDraftOf(stored))).toEqual({
      mode: "hybrid",
      ai_enabled: true,
      llm: null,
      judge: null,
      reranker: "tei:bge:v2",
      rerank_top_n: 8,
      repo_guidance: "off",
      budgets: { ...NO_BUDGETS, monthly_tokens: 1000 },
    });
    const bad = {
      ...retrievalDraftOf(stored),
      rerankTopN: "500",
      dailyTokens: "1.5",
      monthlyUsd: "-1",
    };
    const raised = { ...retrievalDraftOf(stored), dailyUsd: "5", monthlyUsd: "3" };
    expect(
      validateRetrieval(
        raised,
        { ...NO_BUDGETS, daily_usd: 2, monthly_usd: 2 },
        {
          ...NO_BUDGETS,
          daily_usd: 4,
        },
      ),
    ).toEqual({
      dailyUsd: "The instance allows a library at most 2 USD.", // raised past the stored 4
      monthlyUsd: "The instance allows a library at most 2 USD.", // none stored
    });
    expect(validateRetrieval(bad, stored.budget_ceilings)).toEqual({
      rerankTopN: "Enter a whole number from 1 to 200, or leave it empty.",
      dailyTokens: "Enter a whole number of tokens above 0, or leave it empty.",
      monthlyUsd: "Enter an amount above 0, or leave it empty.",
    });
  });

  it("maps a refused save to words", () => {
    const e = (code: string) =>
      new HttpError(422, "/v1/x", { error: code, detail: "the words", fields: [] });
    expect(explainRetrievalSave(e("mode_unavailable"))).toEqual({
      field: "mode",
      message: "the words",
    });
    expect(explainRetrievalSave(e("budget_above_instance")).message).toBe("the words");
    expect(explainRetrievalSave(e("provider_unsupported")).message).toBe("the words");
    expect(explainRetrievalSave(new TypeError("offline")).message).toMatch(/Can't reach/);
  });
});
