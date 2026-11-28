import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { relativeTime } from "@/shared/lib/time";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { LibrariesPage } from "./index";
import { syncOf } from "./model/library";

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
    article_count: 1234,
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
    if (url.includes("/v1/libraries?")) {
      return Response.json({ libraries, next_cursor: null, total: libraries.length });
    }
    if (url.endsWith("/v1/jobs/latest")) {
      return Response.json({ jobs: typeof jobs === "function" ? jobs() : jobs });
    }
    if (url.includes("/v1/jobs/")) {
      // One job with its skipped files: a failure's details.
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

/** The header's line about the list (the pagination has a live region of its own). */
const summary = () => document.querySelector("header [role=status]");

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <Suspense fallback="loading">
            <TestRouter
              pages={{
                "/": LibrariesPage,
                "/libraries/new": () => <p>Add page</p>,
                "/libraries/$owner/$repo": () => <p>Browse page</p>,
                "/libraries/$owner/$repo/settings": () => <p>Settings page</p>,
                "/jobs": () => <p>Jobs page</p>,
              }}
            />
          </Suspense>
        </TooltipProvider>
      </QueryClientProvider>,
    ),
  };
}

describe("libraries slice", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists a library with its default version, when it was imported and its sync", async () => {
    const fetchMock = serve([library()], [job()]);
    renderPage();

    const table = await screen.findByRole("table", { name: "Libraries" });
    const link = await within(table).findByRole("link", { name: "Payments" });
    expect(link).toHaveAttribute("href", "/libraries/acme/payments");
    const row = link.closest("tr");
    if (!row) throw new Error("no row");
    expect(within(row).getByText("/acme/payments")).toBeInTheDocument();
    expect(within(row).getByText("v1.4.0")).toBeInTheDocument();
    expect(within(row).getByText("a1b2c3d")).toBeInTheDocument();
    expect(within(row).getByText("3")).toBeInTheDocument();
    expect(within(row).getByText("1,234")).toBeInTheDocument();
    expect(within(row).getByText("3 days ago")).toBeInTheDocument();
    expect(await within(row).findByText("Synced")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/libraries?limit=20&offset=0",
      expect.anything(),
    );
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs/latest", expect.anything());
    // One request for every library's sync, never one per library.
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes("jobs"))).toHaveLength(1);
    expect(summary()).toHaveTextContent("1 library");
  });

  it("counts the default version's articles in a sortable column", async () => {
    serve([library(), library({ id: "/acme/empty", title: "Empty", article_count: 0 })]);
    renderPage();
    const table = await screen.findByRole("table", { name: "Libraries" });
    expect(within(table).getByRole("columnheader", { name: /Articles/ })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Sort by Articles" })).toBeInTheDocument();
    const count = await within(table).findByText("1,234");
    // It makes room below `lg`, like the versions count.
    expect(count.closest("td")).toHaveClass("max-lg:hidden");
    const empty = (await within(table).findByRole("link", { name: "Empty" })).closest("tr");
    expect(within(empty as HTMLElement).getByText("0")).toHaveClass("text-muted-foreground");
  });

  it("says the articles in words on a phone card", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: query === "(max-width: 47.99rem)",
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      })),
    );
    serve([library(), library({ id: "/acme/one", title: "One", article_count: 1 })]);
    renderPage();
    const cards = await screen.findByRole("list", { name: "Libraries" });
    const [many, one] = within(cards).getAllByRole("listitem") as HTMLElement[];
    expect(many).toHaveTextContent("Articles: 1,234 articles");
    expect(one).toHaveTextContent("Articles: 1 article");
  });

  it("shows a library's logo beside its name, and the generic mark when it has none", async () => {
    serve([library({ logo: "0123456789abcdef" }), library({ id: "/acme/docs", title: "Docs" })]);
    renderPage();
    const withLogo = (await screen.findByRole("link", { name: "Payments" })).closest("tr");
    expect(withLogo?.querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/libraries/acme/payments/logo?v=0123456789abcdef",
    );
    expect(withLogo?.querySelector("img")).toHaveAttribute("alt", "");
    const without = screen.getByRole("link", { name: "Docs" }).closest("tr");
    expect(without?.querySelector("img")).toBeNull();
  });

  it("says when the default version is pinned", async () => {
    serve([library({ default_pinned: true })], [job()]);
    renderPage();

    const row = (await screen.findByRole("link", { name: "Payments" })).closest("tr");
    if (!row) throw new Error("no row");
    expect(row).toHaveTextContent("v1.4.0");
    expect(row).toHaveTextContent("(pinned default)");
  });

  it("shows a failed sync calmly and reveals the reason on demand", async () => {
    serve(
      [library()],
      [job({ state: "failed", error: "git fetch failed: repository not found", skipped: 1 })],
    );
    renderPage();

    const toggle = await screen.findByRole("button", { name: /Sync failed/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(summary()).toHaveTextContent("1 library · 1 sync failed");
    expect(screen.queryByText("git fetch failed: repository not found")).not.toBeInTheDocument();
    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const details = await screen.findByRole("dialog", {
      name: "Why the sync of /acme/payments failed",
    });
    expect(within(details).getByText("git fetch failed: repository not found")).toBeInTheDocument();
    expect(await within(details).findByText("docs/broken.md")).toBeInTheDocument();
    expect(within(details).getByText("Skipped files (1)")).toBeInTheDocument();
    expect(within(details).queryByText("docs/odd.md")).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
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
      await userEvent.click(await screen.findByRole("button", { name: /Tag moved/ }));
      expect(
        await screen.findByRole("link", { name: "Review the moved tag in settings" }),
      ).toBeInTheDocument();
      await userEvent.click(
        screen.getByRole("button", { name: "Re-import the new commit of v1.4.0" }),
      );

      expect(calls).toHaveLength(1);
      expect(calls[0]?.url).toBe("/api/v1/libraries/acme/payments/versions/reimport");
      expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ ref: "v1.4.0" });
      // The queued re-import is the version's newest job: the error gives way to it.
      expect(await screen.findByText("Queued")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Tag moved/ })).not.toBeInTheDocument();
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
      await userEvent.click(await screen.findByRole("button", { name: /Tag moved/ }));
      await userEvent.click(
        await screen.findByRole("button", { name: "Re-import the new commit of v1.4.0" }),
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
      await userEvent.click(await screen.findByRole("button", { name: /Tag moved/ }));
      await userEvent.click(
        await screen.findByRole("button", { name: "Re-import the new commit of v1.4.0" }),
      );
      expect(await screen.findByText(/nothing to re-import/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Re-import/ })).not.toBeInTheDocument();
    });

    it("is not offered for other failures", async () => {
      serve([library()], [job({ state: "failed", error_code: "ref_deleted", error: "gone" })]);
      renderPage();
      await userEvent.click(await screen.findByRole("button", { name: /Sync failed/ }));
      expect(
        await screen.findByRole("link", { name: "Open settings to sync again" }),
      ).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Re-import/ })).not.toBeInTheDocument();
      // The error code stays visible in the row.
      expect(screen.getByText("ref_deleted")).toBeInTheDocument();
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
    expect(
      screen.getByRole("progressbar", { name: "Import progress for /acme/payments" }),
    ).toHaveAttribute("aria-valuenow", "30");
    expect(summary()).toHaveTextContent("1 importing");
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
      const dialog = screen.getByRole("alertdialog", { name: "Cancel the sync of v1.4.0?" });
      await userEvent.click(within(dialog).getByRole("button", { name: "Yes, cancel" }));

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
      url.includes("/v1/libraries?")
        ? Response.json({ libraries: [library()], next_cursor: null, total: 1 })
        : new Response("{}", { status: 500 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    expect(await screen.findByText(/Couldn't load sync status/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Retry" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Payments" })).toBeInTheDocument();
    expect(screen.getByText("Sync status unavailable")).toBeInTheDocument();
  });

  it("teaches how to add a library when there are none", async () => {
    serve([]);
    renderPage();

    expect(await screen.findByText(/exactdocs add https:\/\/github\.com/)).toBeInTheDocument();
  });

  it("offers each library's actions in its menu and syncs one now", async () => {
    const latest = serve([library()], [job()]);
    const posts: string[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(url);
        return Response.json(
          {
            library_id: "/acme/payments",
            versions: [{ ref: "main", ref_kind: "branch", status: "queued" }],
          },
          { status: 202 },
        );
      }
      return latest(url);
    });
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "More actions for /acme/payments" }),
    );
    const menu = await screen.findByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((i) => i.textContent),
    ).toEqual([
      "Open library",
      "Settings",
      "Sharing",
      "Sync now",
      "Show its jobs",
      "Copy library ID",
      "Open the repository",
    ]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Sync now" }));
    await waitFor(() => expect(posts).toEqual(["/api/v1/libraries/acme/payments/sync"]));

    await userEvent.click(screen.getByRole("button", { name: "More actions for /acme/payments" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Settings" }));
    expect(await screen.findByText("Settings page")).toBeInTheDocument();
  });

  it("opens the same actions in a context menu from the keyboard", async () => {
    serve([library()], [job()]);
    renderPage();
    const link = await screen.findByRole("link", { name: "Payments" });
    link.focus();

    await userEvent.keyboard("{Shift>}{F10}{/Shift}");

    const menu = await screen.findByRole("menu");
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Show its jobs" }));
    expect(await screen.findByText("Jobs page")).toBeInTheDocument();
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
      await waitFor(() =>
        expect(
          fetchMock.mock.calls.filter(([u]) => String(u).includes("/v1/libraries?")).length,
        ).toBe(2),
      );

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
