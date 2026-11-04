import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LibrariesPage } from "./index";
import { relativeTime } from "./model/time";

const library = (over: Record<string, unknown> = {}) => ({
  id: "/acme/payments",
  title: "Payments",
  description: "",
  versions: ["main", "v1.3.0", "v1.4.0"],
  default_version: "v1.4.0",
  last_imported_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
  ...over,
});

const job = (over: Record<string, unknown> = {}) => ({
  id: "j1",
  kind: "import",
  library: "/acme/payments",
  version: "v1.4.0",
  state: "succeeded",
  done: 4,
  total: 4,
  problems: [],
  error: null,
  created_at: "2026-11-01T10:00:00Z",
  started_at: "2026-11-01T10:00:01Z",
  finished_at: "2026-11-01T10:01:00Z",
  ...over,
});

function serve(libraries: unknown[], jobs: Record<string, unknown[]> = {}) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/v1/libraries")) return Response.json({ libraries, next_cursor: null });
    const found = Object.entries(jobs).find(([id]) => url.includes(`/libraries${id}/jobs`));
    return Response.json({ jobs: found?.[1] ?? [], next_cursor: null });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <Suspense fallback="loading">
        <LibrariesPage />
      </Suspense>
    </QueryClientProvider>,
  );
}

describe("libraries slice", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists a library with its versions, the default marked and first, and when it was imported", async () => {
    const fetchMock = serve([library()], { "/acme/payments": [job()] });
    renderPage();

    const row = (await screen.findByRole("heading", { name: "/acme/payments" })).closest("li");
    if (!row) throw new Error("no row");
    const versions = within(within(row).getByRole("list", { name: "Versions" })).getAllByRole(
      "listitem",
    );
    expect(versions.map((v) => v.textContent)).toEqual(["v1.4.0 (default)", "main", "v1.3.0"]);
    expect(within(row).getByText("3 days ago")).toBeInTheDocument();
    expect(await within(row).findByText(/Synced/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/libraries", expect.anything());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/libraries/acme/payments/jobs?limit=5",
      expect.anything(),
    );
  });

  it("shows a failed sync calmly and reveals the reason on demand", async () => {
    serve([library()], {
      "/acme/payments": [
        job({
          state: "failed",
          error: "git fetch failed: repository not found",
          problems: [{ path: "docs/broken.md", reason: "invalid front matter" }],
        }),
      ],
    });
    renderPage();

    const toggle = await screen.findByRole("button", { name: /Sync failed/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("status")).toHaveTextContent("1 library · 1 sync failed");
    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("git fetch failed: repository not found")).toBeInTheDocument();
    expect(screen.getByText("docs/broken.md")).toBeInTheDocument();
  });

  it("does not report an old failure that a newer sync fixed", async () => {
    serve([library()], {
      "/acme/payments": [job({ id: "new" }), job({ id: "old", state: "failed", error: "boom" })],
    });
    renderPage();

    expect(await screen.findByText(/Synced/)).toBeInTheDocument();
    expect(screen.queryByText(/Sync failed/)).not.toBeInTheDocument();
  });

  it("shows the progress of a running import", async () => {
    serve([library()], {
      "/acme/payments": [job({ state: "running", done: 12, total: 40, finished_at: null })],
    });
    renderPage();

    expect(await screen.findByText("Importing 12 of 40")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "12");
    expect(screen.getByRole("status")).toHaveTextContent("1 importing");
  });

  it("keeps the list when only the job status is unavailable", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      url.endsWith("/v1/libraries")
        ? Response.json({ libraries: [library()], next_cursor: null })
        : new Response("{}", { status: 500 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    expect(await screen.findByText(/Status unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "/acme/payments" })).toBeInTheDocument();
  });

  it("teaches how to add a library when there are none", async () => {
    serve([]);
    renderPage();

    expect(await screen.findByText(/exactdocs add https:\/\/github\.com/)).toBeInTheDocument();
  });

  it("collapses a long version list behind a count", async () => {
    const versions = Array.from({ length: 12 }, (_, i) => `v1.${i}.0`);
    serve([library({ versions, default_version: "v1.11.0" })]);
    renderPage();

    const more = await screen.findByRole("button", { name: "+7 more" });
    await userEvent.click(more);
    expect(screen.getAllByRole("listitem").some((li) => li.textContent === "v1.0.0")).toBe(true);
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-11-04T12:00:00Z");
  it.each([
    ["2026-11-04T11:59:40Z", "just now"],
    ["2026-11-04T11:15:00Z", "45 minutes ago"],
    ["2026-11-04T09:00:00Z", "3 hours ago"],
    ["2026-11-03T12:00:00Z", "yesterday"],
    ["2026-09-04T12:00:00Z", "2 months ago"],
  ])("%s is %s", (iso, text) => {
    expect(relativeTime(iso, now)).toBe(text);
  });
});
