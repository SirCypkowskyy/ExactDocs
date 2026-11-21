import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { relativeTime } from "@/shared/lib/time";
import { LibrariesPage } from "./index";
import { orderedVersions, syncOf } from "./model/library";

const SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";
const library = (over: Record<string, unknown> = {}) => {
  const versions = (over.versions as string[] | undefined) ?? ["main", "v1.3.0", "v1.4.0"];
  return {
    id: "/acme/payments",
    title: "Payments",
    description: "",
    default_version: "v1.4.0",
    default_pinned: false,
    source_url: "https://github.com/acme/payments.git",
    version_count: versions.length,
    refs: versions.map((ref) => ({
      ref,
      kind: ref === "main" ? "branch" : "tag",
      commit_sha: SHA,
      imported_at: "2026-11-01T10:00:00Z",
      is_default: ref === "v1.4.0",
    })),
    tags: ["api", "guide"],
    last_imported_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
    ...over,
  };
};

const job = (over: Record<string, unknown> = {}) => ({
  id: "j1",
  kind: "import",
  library: "/acme/payments",
  version: "v1.4.0",
  state: "succeeded",
  done: 4,
  total: 4,
  skipped: 0,
  error: null,
  created_at: "2026-11-01T10:00:00Z",
  started_at: "2026-11-01T10:00:01Z",
  finished_at: "2026-11-01T10:01:00Z",
  ...over,
});

/** `jobs` is what `/jobs/latest` answers; a function lets a test change it between polls. */
function serve(libraries: unknown[], jobs: unknown[] | (() => unknown[]) = []) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/v1/libraries")) return Response.json({ libraries, next_cursor: null });
    if (url.endsWith("/v1/jobs/latest")) {
      return Response.json({ jobs: typeof jobs === "function" ? jobs() : jobs });
    }
    if (url.includes("/v1/jobs/")) {
      return Response.json({
        ...job(),
        problems: [
          { path: "docs/broken.md", code: "undecodable", reason: "not text", is_skip: true },
          { path: "docs/odd.md", code: "front_matter", reason: "bad tags", is_skip: false },
        ],
      });
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <Suspense fallback="loading">
          <TestRouter
            pages={{
              "/": LibrariesPage,
              "/libraries/new": () => <p>Add page</p>,
              "/libraries/acme/payments": () => <p>Browse page</p>,
            }}
          />
        </Suspense>
      </QueryClientProvider>,
    ),
  };
}

describe("libraries slice", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists a library with its versions, the default marked and first, and when it was imported", async () => {
    const fetchMock = serve([library()], [job()]);
    renderPage();

    const row = (await screen.findByRole("heading", { name: "Payments" })).closest("li");
    if (!row) throw new Error("no row");
    expect(within(row).getByRole("link", { name: "Payments" })).toHaveAttribute(
      "href",
      "/libraries/acme/payments",
    );
    const versions = within(within(row).getByRole("list", { name: "Versions" })).getAllByRole(
      "listitem",
    );
    expect(versions.map((v) => v.textContent)).toEqual([
      "v1.4.0 (default)a1b2c3d",
      "v1.3.0",
      "main",
    ]);
    expect(within(row).getByText("3 days ago")).toBeInTheDocument();
    expect(await within(row).findByText(/Synced/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/libraries", expect.anything());
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs/latest", expect.anything());
    // One request for every library's sync, never one per library.
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes("jobs"))).toHaveLength(1);
    expect(within(row).getByRole("link", { name: /github\.com\/acme\/payments/ })).toHaveAttribute(
      "href",
      "https://github.com/acme/payments.git",
    );
    expect(within(row).getByText("a1b2c3d")).toBeInTheDocument();
    expect(within(row).getByText("api · guide")).toBeInTheDocument();
  });

  it("says when the default version is pinned", async () => {
    serve([library({ default_pinned: true })], [job()]);
    renderPage();

    const row = (await screen.findByRole("heading", { name: "Payments" })).closest("li");
    if (!row) throw new Error("no row");
    const [first] = within(within(row).getByRole("list", { name: "Versions" })).getAllByRole(
      "listitem",
    );
    expect(first).toHaveTextContent("v1.4.0 (pinned default)");
    expect(first).toHaveAttribute("title", expect.stringMatching(/^Pinned default version/));
  });

  it("shows a failed sync calmly and reveals the reason on demand", async () => {
    serve(
      [library()],
      [job({ state: "failed", error: "git fetch failed: repository not found", skipped: 1 })],
    );
    renderPage();

    const toggle = await screen.findByRole("button", { name: /Sync failed/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("status")).toHaveTextContent("1 library · 1 sync failed");
    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByText("git fetch failed: repository not found").length).toBeGreaterThan(0);
    expect(await screen.findByText("docs/broken.md")).toBeInTheDocument();
    expect(screen.getByText("Skipped files (1)")).toBeInTheDocument();
    expect(screen.queryByText("docs/odd.md")).not.toBeInTheDocument();
  });

  describe("a moved tag", () => {
    const moved = job({
      id: "f1",
      kind: "refresh",
      state: "failed",
      error_code: "tag_moved",
      error: "the tag 'v1.4.0' now points at commit b",
    });

    /** `serve`, plus the re-import answer; `jobs` changes once the re-import was asked. */
    function serveMoved(answer: { status: number; body: unknown }, { stale = false } = {}) {
      let asked = false;
      const latest = serve([library()], () =>
        asked && answer.status === 202 && !stale
          ? [job({ id: "r1", kind: "refresh", state: "queued" })]
          : [moved],
      );
      const calls: { url: string; init?: RequestInit }[] = [];
      vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string, init?: RequestInit) => {
          if (init?.method === "POST") {
            calls.push({ url, init });
            asked = true;
            return Response.json(answer.body, { status: answer.status });
          }
          return latest(url);
        }),
      );
      return calls;
    }

    it("is re-imported at its new commit right from its error", async () => {
      const calls = serveMoved({
        status: 202,
        body: {
          library_id: "/acme/payments",
          ref: "v1.4.0",
          ref_kind: "tag",
          previous_commit_sha: SHA,
          commit_sha: "f".repeat(40),
          job_id: "r1",
        },
      });
      renderPage();
      await userEvent.click(await screen.findByRole("button", { name: /Sync failed/ }));
      expect(
        screen.getByRole("link", { name: "Review the moved tag in settings" }),
      ).toBeInTheDocument();
      await userEvent.click(
        screen.getByRole("button", { name: "Re-import the new commit of v1.4.0" }),
      );

      expect(calls).toHaveLength(1);
      expect(calls[0]?.url).toBe("/api/v1/libraries/acme/payments/versions/reimport");
      expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ ref: "v1.4.0" });
      // The queued re-import is the version's newest job: the error gives way to it.
      expect(await screen.findByText("Queued")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Sync failed/ })).not.toBeInTheDocument();
    });

    it("says it is queued while the list still shows the old error", async () => {
      const calls = serveMoved(
        {
          status: 202,
          body: {
            library_id: "/acme/payments",
            ref: "v1.4.0",
            ref_kind: "tag",
            previous_commit_sha: SHA,
            commit_sha: "f".repeat(40),
            job_id: "r1",
          },
        },
        { stale: true }, // the refetch has not caught up yet
      );
      renderPage();
      await userEvent.click(await screen.findByRole("button", { name: /Sync failed/ }));
      await userEvent.click(
        screen.getByRole("button", { name: "Re-import the new commit of v1.4.0" }),
      );
      expect(
        await screen.findByText("Queued: the new commit of v1.4.0 is being imported."),
      ).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Re-import/ })).not.toBeInTheDocument();
      expect(calls).toHaveLength(1);
    });

    it("says why when the tag moved back, and offers no retry", async () => {
      serveMoved({
        status: 409,
        body: { error: "tag_not_moved", detail: "x", fields: [], close_matches: [] },
      });
      renderPage();
      await userEvent.click(await screen.findByRole("button", { name: /Sync failed/ }));
      await userEvent.click(
        screen.getByRole("button", { name: "Re-import the new commit of v1.4.0" }),
      );
      expect(await screen.findByText(/nothing to re-import/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Re-import/ })).not.toBeInTheDocument();
    });

    it("is not offered for other failures", async () => {
      serve([library()], [job({ state: "failed", error_code: "ref_deleted", error: "gone" })]);
      renderPage();
      await userEvent.click(await screen.findByRole("button", { name: /Sync failed/ }));
      expect(screen.queryByRole("button", { name: /Re-import/ })).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Open settings to sync again" })).toBeInTheDocument();
    });
  });

  it("keeps a failed version visible when another version synced", async () => {
    serve(
      [library()],
      [
        job({ id: "j2", version: "v1.4.0", state: "failed", error: "boom" }),
        job({ id: "j3", version: "main" }),
      ],
    );
    renderPage();

    expect(await screen.findByRole("button", { name: /Sync failed/ })).toBeInTheDocument();
  });

  it("says how many files a synced library skipped", async () => {
    serve([library()], [job({ skipped: 2 })]);
    renderPage();

    expect(await screen.findByText("Synced, 2 skipped")).toBeInTheDocument();
  });

  it("shows the progress of a running import", async () => {
    serve([library()], [job({ state: "running", done: 12, total: 40, finished_at: null })]);
    renderPage();

    expect(await screen.findByText("Importing 12 of 40")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "12");
    expect(screen.getByRole("status")).toHaveTextContent("1 importing");
  });

  describe("cancelling a job from the list (#432)", () => {
    const live = (over: Record<string, unknown>) =>
      job({
        state: "running",
        done: 12,
        total: 40,
        finished_at: null,
        cancelled_at: null,
        cancellable: true,
        ...over,
      });

    it.each(["running", "queued"])("cancels a %s job after a confirmation", async (state) => {
      const latest = serve([library()], [live({ state })]);
      const calls: string[] = [];
      vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          calls.push(url);
          return Response.json(live({ state, cancelled_at: "2026-11-01T10:00:05Z" }));
        }
        return latest(url);
      });
      renderPage();

      await userEvent.click(await screen.findByRole("button", { name: /cancel the sync/i }));
      expect(calls).toEqual([]);
      await userEvent.click(screen.getByRole("button", { name: "Yes, cancel" }));

      expect(calls).toEqual(["/api/v1/jobs/j1/cancel"]);
      expect(await screen.findByText(/Cancelling after the current step/)).toBeInTheDocument();
    });

    it("hides the button from a caller without the role", async () => {
      serve([library()], [live({ cancellable: false })]);
      renderPage();

      expect(await screen.findByText("Importing 12 of 40")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
    });

    it("says who cancelled a sync", async () => {
      serve([library()], [job({ state: "cancelled", cancelled_by: "admin", cancellable: false })]);
      renderPage();

      expect(await screen.findByText("Sync cancelled by admin")).toBeInTheDocument();
    });
  });

  it("keeps the list when only the job status is unavailable", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      url.endsWith("/v1/libraries")
        ? Response.json({ libraries: [library()], next_cursor: null })
        : new Response("{}", { status: 500 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    expect(await screen.findByText(/Couldn't load sync status/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Retry" })).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Payments" })).toBeInTheDocument();
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

    const more = await screen.findByRole("button", {
      name: "Show 7 more versions of /acme/payments",
    });
    await userEvent.click(more);
    expect(screen.getAllByRole("listitem").some((li) => li.textContent === "v1.0.0")).toBe(true);
  });

  it("polls every 2s while a job runs, stops when it ends and refreshes the list", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let state = "running";
      const fetchMock = serve([library()], () => [job({ state, finished_at: null })]);
      renderPage();
      await screen.findByText(/Importing/);
      const count = (suffix: string) =>
        fetchMock.mock.calls.filter(([u]) => String(u).endsWith(suffix)).length;

      await act(() => vi.advanceTimersByTimeAsync(2100));
      expect(count("/jobs/latest")).toBe(2);

      state = "succeeded";
      await act(() => vi.advanceTimersByTimeAsync(2100));
      await screen.findByText("Synced");
      await waitFor(() => expect(count("/v1/libraries")).toBe(2));

      const polled = count("/jobs/latest");
      await act(() => vi.advanceTimersByTimeAsync(6000));
      expect(count("/jobs/latest")).toBe(polled);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not poll after a failure", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const fetchMock = serve([library()], [job({ state: "failed", error: "x" })]);
      renderPage();
      await screen.findByRole("button", { name: /Sync failed/ });
      await act(() => vi.advanceTimersByTimeAsync(6000));
      expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/jobs/latest"))).toHaveLength(
        1,
      );
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("orderedVersions", () => {
  it("puts the default first, tags by semver descending, then branches", () => {
    const lib = library({
      versions: ["main", "v2.9.0", "canary", "v2.10.0", "v2.1.0", "v1.4.0"],
      default_version: "v2.1.0",
    });
    lib.refs = lib.refs.map((r) => ({
      ...r,
      kind: r.ref === "main" || r.ref === "canary" ? "branch" : "tag",
    }));
    expect(orderedVersions(lib as never)).toEqual([
      "v2.1.0",
      "v2.10.0",
      "v2.9.0",
      "v1.4.0",
      "canary",
      "main",
    ]);
  });
});

describe("syncOf", () => {
  const j = (over: Record<string, unknown>) => job(over) as never;
  it("is failed when any version failed, running when none did", () => {
    expect(syncOf([j({ id: "1", state: "failed" }), j({ id: "2" })]).kind).toBe("failed");
    expect(syncOf([j({ state: "running" }), j({ id: "2" })]).kind).toBe("running");
    expect(syncOf([]).kind).toBe("none");
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
    ["2026-09-25T12:00:00Z", "40 days ago"],
    ["2026-11-04T12:05:00Z", "just now"],
    ["2026-11-04T11:00:20Z", "59 minutes ago"],
    ["2026-11-03T12:20:00Z", "23 hours ago"],
    ["2025-11-09T12:00:00Z", "11 months ago"],
  ])("%s is %s", (iso, text) => {
    expect(relativeTime(iso, now)).toBe(text);
  });
});
