import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JobLine } from "./index";

const job = (over: Record<string, unknown>) => ({
  id: "j1",
  kind: "refresh",
  library: "/acme/payments",
  version: "main",
  commit_sha: null,
  state: "running",
  done: 2,
  total: 5,
  problems: [],
  error: null,
  created_at: "2026-11-01T10:00:00Z",
  started_at: "2026-11-01T10:00:01Z",
  finished_at: null,
  ...over,
});

function renderLine(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json(body)),
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <JobLine jobId="j1" label="main" />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("a re-sync job line", () => {
  it("shows progress while the job runs and announces nothing yet", async () => {
    renderLine(job({}));
    expect(await screen.findByText("2 of 5 files")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /main/ })).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("says how it ended, and announces it once", async () => {
    renderLine(job({ state: "succeeded", done: 5, finished_at: "2026-11-01T10:01:00Z" }));
    expect(await screen.findByText("5 files imported")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("main: Import finished. 5 files imported");
  });

  it("shows why a job failed", async () => {
    renderLine(
      job({ state: "failed", error: "git fetch failed", finished_at: "2026-11-01T10:01:00Z" }),
    );
    expect(await screen.findByText(/Stopped after 2 of 5 files/)).toBeInTheDocument();
    expect(screen.getAllByText(/git fetch failed/).length).toBeGreaterThan(0);
  });
});
