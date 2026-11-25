import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { JobsPage, parseJobsView } from "./index";
import { jobsFilters, jobsParams } from "./model/jobs-view";

const job = (n: number, over: Record<string, unknown> = {}) => ({
  id: `j${n}`,
  kind: "import",
  library: `/acme/lib${n}`,
  version: "v1.0.0",
  commit_sha: null,
  state: "succeeded",
  done: 1,
  total: 1,
  problems: [],
  chunked: 0,
  reused: 0,
  parsed: 1,
  taken: 0,
  error: null,
  error_code: null,
  origin: "manual",
  created_at: "2026-11-01T10:00:00Z",
  started_at: "2026-11-01T10:00:00Z",
  finished_at: "2026-11-01T10:01:00Z",
  cancelled_by: null,
  cancelled_at: null,
  cancellable: false,
  ...over,
});

/**
 * A jobs API over `count` jobs that honours `limit` and an `offset` (or a cursor, `o<n>`, never
 * both), filters by `state` (repeatable) and answers a cancel. Job 2 failed, job 3 is running and may be cancelled.
 */
function serve(count = 45) {
  const all = Array.from({ length: count }, (_, i) =>
    job(i + 1, {
      ...(i === 1 && { state: "failed", error: "unreachable", error_code: "repo_unreachable" }),
      ...(i === 2 && { state: "running", finished_at: null, cancellable: true, done: 2, total: 5 }),
      // Job 1 was queued by alice; jobs 4 and 5 by the instance on its own.
      ...(i === 0 && { created_by: { id: "u1", username: "alice" } }),
      ...((i === 3 || i === 4) && { origin: "auto", created_by: null }),
    }),
  );
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    if (init?.method === "POST") {
      return Response.json({ ...all[2], cancelled_at: "2026-11-01T10:02:00Z", cancellable: false });
    }
    if (url.pathname.endsWith("/v1/libraries")) {
      const q = url.searchParams.get("q") ?? "";
      const libraries = ["/acme/lib1", "/acme/lib3", "/azure/storage"]
        .filter((id) => id.includes(q))
        .map((id) => ({ id, title: id.split("/")[2], logo: null }));
      return Response.json({ libraries, next_cursor: null, total: libraries.length, notice: "" });
    }
    const states = url.searchParams.getAll("state");
    const origins = url.searchParams.getAll("origin");
    const rows = all.filter(
      (j) =>
        (!states.length || states.includes(j.state)) &&
        (!origins.length || origins.includes(j.origin)),
    );
    const offset = url.searchParams.get("offset");
    const cursor = url.searchParams.get("cursor");
    if (offset !== null && cursor !== null) {
      return Response.json({ code: "cursor_with_offset" }, { status: 422 });
    }
    const start = Number(offset ?? cursor?.slice(1) ?? 0);
    const limit = Number(url.searchParams.get("limit"));
    const page = rows.slice(start, start + limit);
    return Response.json({
      jobs: page,
      next_cursor: start + limit < rows.length ? `o${start + limit}` : null,
      total: rows.length,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const urls = (fetchMock: ReturnType<typeof serve>) =>
  fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/v1/jobs?"));

function renderPage(start = "/jobs") {
  const history = createMemoryHistory({ initialEntries: [start] });
  // As in the app: a page fetched ahead stays fresh long enough to be shown without asking again.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <TestRouter
          history={history}
          pages={{ "/jobs": JobsPage, "/libraries/$owner/$repo": () => <p>Browse</p> }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

describe("the jobs table", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("keeps only what the API knows from a hand-edited URL", () => {
    expect(
      parseJobsView({
        state: "failed,queued",
        kind: "embed",
        library: "/a/b",
        sort: "-created_at",
        page: 3,
        size: 50,
        created: "7d",
      }),
    ).toEqual({
      q: undefined,
      sort: "-created_at",
      page: 3,
      size: 50,
      state: ["queued", "failed"],
      kind: ["embed"],
      origin: undefined,
      created: "7d",
      library: "/a/b",
      version: undefined,
    });
    expect(
      parseJobsView({
        state: "lost",
        kind: "x",
        library: "a",
        sort: "password",
        page: -1,
        size: 7,
      }),
    ).toEqual({
      q: undefined,
      sort: undefined,
      page: undefined,
      size: undefined,
      state: undefined,
      kind: undefined,
      origin: undefined,
      created: undefined,
      library: undefined,
      version: undefined,
    });
    const filters = jobsFilters(
      { state: ["failed", "queued"], library: "/a/b", sort: "state", created: "24h" },
      Date.parse("2026-11-02T10:00:30Z"),
    );
    expect(jobsParams(filters, 20, null, 40)).toBe(
      "limit=20&state=failed&state=queued&library=%2Fa%2Fb&created_after=2026-11-01T10%3A00%3A00.000Z&sort=state&offset=40",
    );
    // Past the API's offset bound the table goes on by cursor, and never sends both.
    expect(jobsParams({}, 20, "c1")).toBe("limit=20&cursor=c1");
  });

  it("reads the view from the URL, sends it to the API and shows the total", async () => {
    const fetchMock = serve();
    renderPage("/jobs?state=failed&library=/azure/storage&sort=-created_at");

    const table = await screen.findByRole("table", { name: "Jobs" });
    expect(await within(table).findByRole("link", { name: "/acme/lib2" })).toBeInTheDocument();
    expect(urls(fetchMock)[0]).toBe(
      "/api/v1/jobs?limit=20&state=failed&library=%2Fazure%2Fstorage&sort=-created_at&offset=0",
    );
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(within(chips).getByText("/azure/storage")).toBeInTheDocument();
    expect(
      within(chips).getByRole("button", { name: "Remove filter Library: /azure/storage" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 job")).toBeInTheDocument();
  });

  it("filters by library with the library combobox, and the chip takes it off", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 45");
    const filter = screen.getByRole("button", { name: "Library" });
    await userEvent.click(filter);
    // The libraries are asked for only once the list opens.
    await userEvent.type(screen.getByRole("combobox", { name: "Find a library" }), "lib3");
    const listbox = screen.getByRole("listbox", { name: "Library" });
    // The typed text goes to the API (after a short rest), which searches every library.
    const libraryUrls = () =>
      fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/v1/libraries?"));
    await waitFor(() =>
      expect(libraryUrls()).toEqual([
        "/api/v1/libraries?limit=200&sort=id",
        "/api/v1/libraries?limit=200&sort=id&q=lib3",
      ]),
    );
    expect(within(listbox).getAllByRole("option")).toHaveLength(1);
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(history.location.search).toContain("library=%2Facme%2Flib3"));
    await waitFor(() =>
      expect(urls(fetchMock).at(-1)).toBe("/api/v1/jobs?limit=20&library=%2Facme%2Flib3&offset=0"),
    );
    const trigger = screen.getByRole("button", { name: "Library: /acme/lib3" });
    await waitFor(() => expect(trigger).toHaveFocus());
    const chips = screen.getByRole("list", { name: "Active filters" });
    await userEvent.click(
      within(chips).getByRole("button", { name: "Remove filter Library: /acme/lib3" }),
    );
    await waitFor(() => expect(history.location.search).not.toContain("library"));
    expect(screen.getByRole("button", { name: "Library" })).toBeInTheDocument();
  });

  it("pages with numbered pages, the next one fetched ahead", async () => {
    const fetchMock = serve();
    const history = renderPage();
    expect(await screen.findByText("1–20 of 45")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Jobs" })).toHaveAttribute("aria-rowcount", "46");
    // The next page is asked for in the background, by its offset (never a cursor).
    await waitFor(() => expect(urls(fetchMock)).toContain("/api/v1/jobs?limit=20&offset=20"));
    const asked = urls(fetchMock).length;

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByText("21–40 of 45")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "/acme/lib21" })).toBeInTheDocument();
    expect(history.location.search).toContain("page=2");
    // Already fetched: Next costs nothing.
    expect(urls(fetchMock).slice(asked)).not.toContain("/api/v1/jobs?limit=20&offset=20");
    // Focus stays on the button; the move is announced.
    expect(screen.getByRole("button", { name: "Next page" })).toHaveFocus();
    expect(screen.getByText("Page 2 of 3", { selector: "[role=status]" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Page 2" })).toHaveAttribute("aria-current", "page");

    await userEvent.click(screen.getByRole("button", { name: "First page" }));
    expect(await screen.findByText("1–20 of 45")).toBeInTheDocument();
    expect(history.location.search).not.toContain("page=");
    expect(urls(fetchMock).every((u) => !u.includes("cursor="))).toBe(true);
  });

  it("jumps to the last page with one request", async () => {
    const fetchMock = serve(233);
    const history = renderPage();
    await screen.findByText("1–20 of 233");
    const asked = urls(fetchMock).length;

    await userEvent.click(screen.getByRole("button", { name: "Last page" }));

    // docs/rest-api/pagination.md's example: 233 jobs, 20 a page, the last one is offset 220 (13 jobs).
    expect(await screen.findByText("221–233 of 233")).toBeInTheDocument();
    expect(urls(fetchMock)[asked]).toBe("/api/v1/jobs?limit=20&offset=220");
    expect(history.location.search).toContain("page=12");
  });

  it("opens a page from a link with one request, and keeps the size in the URL", async () => {
    const fetchMock = serve();
    const history = renderPage("/jobs?page=3");
    expect(await screen.findByText("41–45 of 45")).toBeInTheDocument();
    // Page 3 by its offset: no walk from the start.
    expect(urls(fetchMock)[0]).toBe("/api/v1/jobs?limit=20&offset=40");
    expect(screen.getByRole("button", { name: "Next page" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );

    await userEvent.selectOptions(screen.getByLabelText("Rows per page"), "50");

    expect(await screen.findByText("1–45 of 45")).toBeInTheDocument();
    expect(history.location.search).toContain("size=50");
    expect(history.location.search).not.toContain("page=");
    expect(urls(fetchMock)).toContain("/api/v1/jobs?limit=50&offset=0");
    expect(JSON.parse(localStorage.getItem("exactdocs-table-sizes") ?? "{}")).toEqual({ jobs: 50 });
  });

  it("sorts on the server and keeps the sort in the URL", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 45");
    // The API's own order, newest first, shows on the ID column.
    expect(screen.getByRole("columnheader", { name: /#/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );

    await userEvent.click(screen.getByRole("button", { name: "Sort by State" }));

    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/jobs?limit=20&sort=state&offset=0"),
    );
    expect(history.location.search).toContain("sort=state");
    expect(screen.getByRole("columnheader", { name: /State/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
  });

  it("filters by several states, shows chips, says when nothing matches and clears", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 45");

    await userEvent.click(screen.getByRole("button", { name: "State" }));
    await userEvent.click(await screen.findByRole("option", { name: "failed" }));
    await userEvent.click(screen.getByRole("option", { name: "running" }));
    await userEvent.keyboard("{Escape}");

    await waitFor(() =>
      expect(urls(fetchMock)).toContain(
        "/api/v1/jobs?limit=20&state=running&state=failed&offset=0",
      ),
    );
    expect(history.location.search).toContain("state=running%2Cfailed");
    expect(screen.getByRole("button", { name: "State, 2 selected" })).toBeInTheDocument();
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(within(chips).getAllByRole("listitem")).toHaveLength(2);
    expect(await screen.findByText("1–2 of 2")).toBeInTheDocument();

    await userEvent.click(
      within(chips).getByRole("button", { name: "Remove filter State: failed" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "State, 1 selected" }));
    await userEvent.click(await screen.findByRole("option", { name: "queued" }));
    await userEvent.click(screen.getByRole("option", { name: "running" }));
    await userEvent.keyboard("{Escape}");

    expect(await screen.findByText("No jobs match")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("1–20 of 45")).toBeInTheDocument();
    expect(history.location.search).toBe("");
  });

  it("names who queued each job, the instance's own work as automatic", async () => {
    serve();
    renderPage();
    const table = await screen.findByRole("table", { name: "Jobs" });
    expect(within(table).getByRole("columnheader", { name: "Started by" })).toBeInTheDocument();
    await within(table).findByRole("link", { name: "/acme/lib1" });
    const rowOf = (library: string) =>
      within(table).getByRole("link", { name: library }).closest("tr") as HTMLElement;
    expect(within(rowOf("/acme/lib1")).getByText("alice")).toBeInTheDocument();
    expect(within(rowOf("/acme/lib4")).getByText("Automatic")).toBeInTheDocument();
    // A manual job without a person: the command line, or from before it was recorded.
    expect(within(rowOf("/acme/lib2")).getByText("Not recorded")).toBeInTheDocument();
  });

  it("filters by origin on the server, in the URL", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("1–20 of 45");

    await userEvent.click(screen.getByRole("button", { name: "Origin" }));
    await userEvent.click(await screen.findByRole("option", { name: "auto" }));
    await userEvent.keyboard("{Escape}");

    await waitFor(() =>
      expect(urls(fetchMock)).toContain("/api/v1/jobs?limit=20&origin=auto&offset=0"),
    );
    expect(history.location.search).toContain("origin=auto");
    expect(await screen.findByText("1–2 of 2")).toBeInTheDocument();
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(within(chips).getByText("auto")).toBeInTheDocument();
  });

  it("reads the origin from a link; both origins are no filter at all", async () => {
    expect(parseJobsView({ origin: "auto,manual,robot" }).origin).toEqual(["manual", "auto"]);
    expect(jobsFilters({ origin: ["manual", "auto"] }, 0)).toEqual({});
    const fetchMock = serve();
    renderPage("/jobs?origin=manual");
    expect(await screen.findByText("1–20 of 43")).toBeInTheDocument();
    expect(urls(fetchMock)[0]).toBe("/api/v1/jobs?limit=20&origin=manual&offset=0");
  });

  it("hides and shows a column", async () => {
    serve();
    renderPage();
    const table = await screen.findByRole("table", { name: "Jobs" });
    expect(within(table).getByRole("columnheader", { name: /Kind/ })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Columns" }));
    await userEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Kind" }));
    await userEvent.keyboard("{Escape}");

    expect(within(table).queryByRole("columnheader", { name: /Kind/ })).not.toBeInTheDocument();
    // Library and state say what a job is: they cannot be hidden.
    await userEvent.click(screen.getByRole("button", { name: "Columns" }));
    expect(screen.queryByRole("menuitemcheckbox", { name: "State" })).not.toBeInTheDocument();
  });

  it("shows states with their detail: the error code, the running progress", async () => {
    serve();
    renderPage();
    const table = await screen.findByRole("table", { name: "Jobs" });
    const failed = (await within(table).findByRole("link", { name: "/acme/lib2" })).closest("tr");
    expect(failed).not.toBeNull();
    expect(within(failed as HTMLElement).getByText("failed")).toBeInTheDocument();
    expect(within(failed as HTMLElement).getByText("repo_unreachable")).toBeInTheDocument();
    const running = within(table).getByRole("link", { name: "/acme/lib3" }).closest("tr");
    expect(
      within(running as HTMLElement).getByRole("progressbar", {
        name: "Progress of the import of /acme/lib3",
      }),
    ).toHaveAttribute("aria-valuenow", "40");
    expect(within(running as HTMLElement).getByText("2 / 5 files")).toBeInTheDocument();
  });

  it("cancels a running job from its menu, behind a confirmation", async () => {
    const fetchMock = serve();
    renderPage();
    await screen.findByText("1–20 of 45");
    // Only a job the caller may cancel offers it.
    await userEvent.click(
      screen.getByRole("button", { name: "More actions for /acme/lib1 v1.0.0 (import)" }),
    );
    expect(await screen.findByRole("menuitem", { name: "Copy job ID" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Cancel job…" })).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    await userEvent.click(
      screen.getByRole("button", { name: "More actions for /acme/lib3 v1.0.0 (import)" }),
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: "Cancel job…" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Cancel this job?" });
    expect(within(dialog).getByRole("button", { name: "Keep it" })).toHaveFocus();
    expect(dialog).toHaveTextContent("It stops after the current step");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel job" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/v1/jobs/j3/cancel"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("opens the same actions in a context menu from the keyboard", async () => {
    serve();
    renderPage();
    const table = await screen.findByRole("table", { name: "Jobs" });
    const link = await within(table).findByRole("link", { name: "/acme/lib1" });
    link.focus();

    await userEvent.keyboard("{Shift>}{F10}{/Shift}");

    const menu = await screen.findByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Open library" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Copy job ID" })).toBeInTheDocument();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Show this library's jobs" }));
    expect(
      await screen.findByRole("button", { name: "Remove filter Library: /acme/lib1" }),
    ).toBeInTheDocument();
  });
});
