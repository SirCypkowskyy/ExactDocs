import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { JobsPage, parseJobsView } from "./index";
import { jobsParams } from "./model/jobs-view";

const job = (n: number, state = "succeeded") => ({
  id: `j${n}`,
  kind: "import",
  library: `/acme/lib${n}`,
  version: "v1.0.0",
  commit_sha: null,
  state,
  done: 1,
  total: 1,
  problems: [],
  chunked: 0,
  reused: 0,
  parsed: 1,
  taken: 0,
  error: state === "failed" ? "unreachable" : null,
  error_code: null,
  origin: "manual",
  created_at: "2026-11-01T10:00:00Z",
  started_at: null,
  finished_at: "2026-11-01T10:01:00Z",
  cancelled_by: null,
  cancelled_at: null,
  cancellable: false,
});

/** Two pages of jobs (cursor "p2" is the second); `state=queued` matches nothing. */
function serve() {
  const fetchMock = vi.fn(async (url: string) => {
    const second = url.includes("cursor=p2");
    const empty = url.includes("state=queued");
    return Response.json({
      jobs: empty ? [] : second ? [job(3)] : [job(1), job(2, "failed")],
      next_cursor: second || empty ? null : "p2",
      total: empty ? 0 : 3,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const urls = (fetchMock: ReturnType<typeof serve>) =>
  fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/v1/jobs?"));

function renderPage(start = "/jobs") {
  const history = createMemoryHistory({ initialEntries: [start] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TestRouter
        history={history}
        pages={{ "/jobs": JobsPage, "/libraries/$owner/$repo": () => <p>Browse</p> }}
      />
    </QueryClientProvider>,
  );
  return history;
}

describe("the jobs table", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps only what the API knows from a hand-edited URL", () => {
    expect(
      parseJobsView({ state: "failed", kind: "embed", library: "/a/b", sort: "-created_at" }),
    ).toEqual({
      q: undefined,
      state: "failed",
      kind: "embed",
      library: "/a/b",
      sort: "-created_at",
    });
    expect(parseJobsView({ state: "lost", kind: "x", library: "a", sort: "password" })).toEqual({
      q: undefined,
      state: undefined,
      kind: undefined,
      library: undefined,
      sort: undefined,
    });
    expect(jobsParams({ state: "failed", library: "/a/b", sort: "state" }, "c1")).toBe(
      "limit=50&state=failed&library=%2Fa%2Fb&sort=state&cursor=c1",
    );
  });

  it("reads the view from the URL, sends it to the API and shows the total", async () => {
    const fetchMock = serve();
    renderPage("/jobs?state=failed&library=/azure/storage&sort=-created_at");

    const table = await screen.findByRole("table", { name: "Jobs" });
    expect(await within(table).findByRole("link", { name: "/acme/lib1" })).toBeInTheDocument();
    expect(urls(fetchMock)[0]).toBe(
      "/api/v1/jobs?limit=50&state=failed&library=%2Fazure%2Fstorage&sort=-created_at",
    );
    expect(screen.getByRole("button", { name: "Show every library" })).toBeInTheDocument();
    expect(screen.getByText("Showing 2 of 3")).toBeInTheDocument();
  });

  it("prefetches the next page and shows it on demand", async () => {
    const fetchMock = serve();
    renderPage();
    await screen.findByText("Showing 2 of 3");
    await waitFor(() => expect(urls(fetchMock)).toHaveLength(2));
    expect(screen.queryByRole("link", { name: "/acme/lib3" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(screen.getByRole("link", { name: "/acme/lib3" })).toBeInTheDocument();
    expect(urls(fetchMock)).toHaveLength(2);
  });

  it("sorts on the server and keeps the sort in the URL", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("Showing 2 of 3");

    await userEvent.click(screen.getByRole("button", { name: "Sort by State" }));

    await waitFor(() => expect(urls(fetchMock)).toContain("/api/v1/jobs?limit=50&sort=state"));
    expect(history.location.search).toContain("sort=state");
    expect(screen.getByRole("columnheader", { name: /State/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
  });

  it("filters on the server, says when nothing matches and clears the filters", async () => {
    const fetchMock = serve();
    const history = renderPage();
    await screen.findByText("Showing 2 of 3");

    await userEvent.selectOptions(screen.getByLabelText("State"), "queued");

    expect(await screen.findByText("No jobs match")).toBeInTheDocument();
    expect(urls(fetchMock)).toContain("/api/v1/jobs?limit=50&state=queued");
    expect(history.location.search).toContain("state=queued");

    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("Showing 2 of 3")).toBeInTheDocument();
    expect(screen.getByLabelText("State")).toHaveValue("");
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
});
