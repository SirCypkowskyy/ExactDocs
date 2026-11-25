import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JobLine } from "./index";

const job = (over: Record<string, unknown>) => ({
  id: "j1",
  kind: "embed",
  library: "/acme/payments",
  version: "v1",
  commit_sha: null,
  state: "running",
  done: 2,
  total: 5,
  problems: [],
  error: null,
  created_at: "2026-11-01T10:00:00Z",
  started_at: "2026-11-01T10:00:01Z",
  finished_at: null,
  cancelled_by: null,
  cancelled_at: null,
  cancellable: true,
  ...over,
});

function renderLine(body: Record<string, unknown>, cancelled?: Record<string, unknown>) {
  const fetch = vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === "POST" ? Response.json(cancelled ?? body) : Response.json(body),
  );
  vi.stubGlobal("fetch", fetch);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <JobLine jobId="j1" label="v1" />
    </QueryClientProvider>,
  );
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

describe("cancelling a job", () => {
  it("asks first, then cancels the running job", async () => {
    const fetch = renderLine(
      job({}),
      job({ cancelled_by: "admin", cancelled_at: "2026-11-01T10:00:05Z", cancellable: false }),
    );
    await userEvent.click(await screen.findByRole("button", { name: /cancel v1/i }));
    const dialog = screen.getByRole("alertdialog", { name: "Cancel v1?" });
    expect(within(dialog).getByText(/stops after the current step/)).toBeInTheDocument();
    // The safe choice has focus first.
    expect(within(dialog).getByRole("button", { name: "Keep it" })).toHaveFocus();
    expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining("/cancel"), expect.anything());

    await userEvent.click(within(dialog).getByRole("button", { name: "Yes, cancel" }));

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/jobs/j1/cancel"),
      expect.objectContaining({ method: "POST" }),
    );
    const status = await screen.findByText(/Cancelling after the current step/);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    // The button that asked is gone: focus lands on what took its place.
    await waitFor(() => expect(status).toHaveFocus());
  });

  it("says inside the confirmation why a cancel was refused", async () => {
    const fetch = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "POST"
        ? Response.json({ error: "job_finished", detail: "x" }, { status: 409 })
        : Response.json(job({ state: "queued", done: 0, total: 0 })),
    );
    vi.stubGlobal("fetch", fetch);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <JobLine jobId="j1" label="v1" />
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /cancel v1/i }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("It has not started, so it never will.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Yes, cancel" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The job ended before it could be cancelled.",
    );
  });

  it("keeps the job when the confirmation is declined", async () => {
    const fetch = renderLine(job({}));
    await userEvent.click(await screen.findByRole("button", { name: /cancel v1/i }));
    await userEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(screen.getByRole("button", { name: /cancel v1/i })).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining("/cancel"), expect.anything());
  });

  it("hides the button from a caller without the role", async () => {
    renderLine(job({ cancellable: false }));
    expect(await screen.findByText("2 of 5 files")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
  });

  it("shows who cancelled a job that ended cancelled", async () => {
    renderLine(
      job({
        state: "cancelled",
        cancelled_by: "admin",
        cancelled_at: "2026-11-01T10:00:05Z",
        finished_at: "2026-11-01T10:00:06Z",
        cancellable: false,
      }),
    );
    expect(await screen.findByText(/Cancelled by admin after 2 of 5/)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
  });
});
