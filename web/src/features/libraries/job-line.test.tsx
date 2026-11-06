import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImportProgress, JobLine } from "./index";

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

describe("a re-processing job line", () => {
  it("counts versions, not files, while a library is re-processed", async () => {
    renderLine(job({ kind: "reprocess", done: 1, total: 2 }));
    expect(await screen.findByText("1 of 2 versions")).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "Re-processing progress for main" }),
    ).toBeInTheDocument();
  });

  it("says how a re-tag ended, in versions", async () => {
    renderLine(
      job({ kind: "retag", state: "succeeded", done: 2, finished_at: "2026-11-01T10:01:00Z" }),
    );
    expect(await screen.findByText("2 versions re-tagged")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "main: Re-tagging finished. 2 versions re-tagged.",
    );
  });

  it("names the versions a failed re-processing stopped at", async () => {
    renderLine(
      job({
        kind: "reprocess",
        state: "failed",
        done: 1,
        total: 2,
        error: "v1.3.0 could not be fetched",
        finished_at: "2026-11-01T10:01:00Z",
      }),
    );
    expect(await screen.findByText(/Stopped after 1 of 2 versions/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Re-processing failed. v1.3.0");
  });
});

describe("an import inside another page", () => {
  it("names the version, offers the page's own exit at once, and leaves the list link out", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(job({ state: "queued", done: 0, total: 0 }))),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ImportProgress
          added={{
            library_id: "/acme/payments",
            ref: "v1.3.0",
            commit_sha: "a1b2c3d4e5f6",
            job_id: "j1",
          }}
          finish={<button type="button">Close</button>}
        />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByRole("heading", { level: 3, name: /Importing v1.3.0/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.queryByText("Back to libraries")).not.toBeInTheDocument();
  });
});
