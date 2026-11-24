import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import {
  AccessLogPage,
  LibraryAccessLogPage,
  parseAccessLogView,
  parseLibraryAccessLogView,
} from "./index";
import {
  type AccessEvent,
  accessLogFilters,
  accessLogParams,
  describeEvent,
  explainAccessLogError,
  whenBounds,
} from "./model/access-log";

const event = (extra: Partial<AccessEvent>): AccessEvent => ({
  id: "e",
  library: "/acme/payments",
  at: "2026-11-22T10:00:00Z",
  actor: "alice",
  change: "granted",
  kind: "user",
  subject: "bob",
  role: "viewer",
  previous_role: null,
  ...extra,
});
const sentence = (e: AccessEvent) =>
  describeEvent(e)
    .map((p) => p.text)
    .join("");
const json = (body: unknown, status = 200) => Response.json(body, { status });

/**
 * An access log API over `events` that filters by `change` (repeatable), `library`, `actor` and
 * `subject`, sorts by `change`, and pages with `limit` and an `offset` (or a cursor, `o<n>`); or
 * one that refuses with `status`.
 */
function stubApi(events: AccessEvent[], status = 200) {
  const fetchMock = vi.fn(async (url: string) => {
    if (status !== 200) return json({ error: "forbidden", detail: "no", fields: [] }, status);
    const params = new URL(url, "http://x").searchParams;
    if (url.startsWith("/api/v1/libraries?")) {
      const q = params.get("q") ?? "";
      const libraries = ["/acme/ledger", "/acme/payments"]
        .filter((id) => id.includes(q))
        .map((id) => ({ id, title: id.split("/")[2], logo: null }));
      return json({ libraries, next_cursor: null, total: libraries.length, notice: "" });
    }
    const changes = params.getAll("change");
    const library = params.get("library");
    const actor = params.get("actor")?.toLowerCase();
    const subject = params.get("subject");
    const shown = events.filter(
      (e) =>
        (changes.length === 0 || changes.includes(e.change)) &&
        (!library || e.library === library) &&
        (!actor || e.actor?.toLowerCase() === actor) &&
        (!subject || e.subject === subject),
    );
    if (params.get("sort") === "change") shown.sort((a, b) => a.change.localeCompare(b.change));
    const start = Number(params.get("offset") ?? params.get("cursor")?.slice(1) ?? 0);
    const limit = Number(params.get("limit"));
    return json({
      events: shown.slice(start, start + limit),
      next_cursor: start + limit < shown.length ? `o${start + limit}` : null,
      total: shown.length,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const asked = (fetchMock: ReturnType<typeof stubApi>) =>
  fetchMock.mock.calls.map(([url]) => String(url));

/** A page under a memory router, as in the app: the table's view lives in the URL. */
function renderAt(page: "all" | "library", search = "", logo: string | null = null) {
  const path = page === "all" ? "/access-log" : "/libraries/acme/payments/access-log";
  const history = createMemoryHistory({ initialEntries: [`${path}${search}`] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TestRouter
          history={history}
          pages={{
            "/access-log": AccessLogPage,
            "/libraries/$owner/$repo/access-log": () => (
              <LibraryAccessLogPage owner="acme" repo="payments" logo={logo} />
            ),
            "/libraries/$owner/$repo": () => <p>Browse</p>,
          }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

/** The table once its rows are in (skeleton rows come first). */
async function rowsOf(label = "Access changes, newest first") {
  const table = await screen.findByRole("table", { name: label });
  await waitFor(() => expect(within(table).getAllByRole("row").length).toBeGreaterThan(1));
  await waitFor(() => expect(table).not.toHaveAttribute("aria-busy"));
  return within(table).getAllByRole("row").slice(1);
}

/** A faceted filter's options. */
const facetOptions = async () => within(await screen.findByRole("listbox")).getAllByRole("option");

describe("access log sentences", () => {
  it("say who did what to whom", () => {
    expect(sentence(event({}))).toBe("alice gave bob the viewer role");
    expect(sentence(event({ role: "contributor", previous_role: "viewer" }))).toBe(
      "alice changed bob from viewer to contributor",
    );
    expect(sentence(event({ change: "revoked", kind: "group", subject: "corp:docs" }))).toBe(
      "alice took the viewer role from the group corp:docs",
    );
    expect(
      sentence(event({ change: "ownership_transferred", subject: "carol", role: "creator" })),
    ).toBe("alice transferred ownership to carol");
    expect(sentence(event({ change: "library_created", subject: "alice", role: "creator" }))).toBe(
      "alice created the library",
    );
    expect(
      sentence(
        event({ change: "library_deleted", actor: null, kind: null, subject: null, role: null }),
      ),
    ).toBe("ExactDocs (command line or a job) removed the library and every role on it");
  });

  it("keep their part keys unique", () => {
    const parts = describeEvent(event({ role: "admin", previous_role: "viewer", kind: "group" }));
    expect(new Set(parts.map((p) => p.key)).size).toBe(parts.length);
  });
});

describe("access log view", () => {
  it("drops anything unknown in the URL", () => {
    expect(
      parseAccessLogView({
        change: "revoked,granted",
        library: "/acme/payments",
        page: 2,
        size: 50,
        q: "x",
        sort: "at",
        actor: " Alice ",
        subject: "corp:docs",
        when: "7d",
      }),
    ).toEqual({
      change: ["granted", "revoked"],
      library: "/acme/payments",
      page: 2,
      size: 50,
      sort: "at",
      actor: "Alice",
      subject: "corp:docs",
      when: "7d",
    });
    expect(parseAccessLogView({ change: "nuked", library: "acme", size: 7 })).toEqual({
      change: undefined,
      library: undefined,
      page: undefined,
      size: undefined,
    });
    expect(
      parseLibraryAccessLogView({
        change: "granted",
        library: "/acme/payments",
        sort: "-library",
        actor: 42,
      }),
    ).toEqual({ change: ["granted"], actor: "42" });
    // Dates: a preset, or real days with at least one end, the start not after the end.
    const when = (value: unknown) => parseAccessLogView({ when: value }).when;
    expect(when("30d")).toBe("30d");
    expect(when("2026-11-01..2026-11-20")).toBe("2026-11-01..2026-11-20");
    expect(when("2026-11-01..")).toBe("2026-11-01..");
    expect(when("..2026-11-20")).toBe("..2026-11-20");
    for (const bad of ["1y", "..", "2026-11-20..2026-11-01", "2026-11-31..", "x..y", 7]) {
      expect(when(bad)).toBeUndefined();
    }
    expect(parseAccessLogView({ sort: "-change" }).sort).toBe("-change");
    expect(parseAccessLogView({ sort: "actor" }).sort).toBeUndefined();
    expect(
      accessLogParams(
        accessLogFilters({ change: ["granted", "revoked"], library: "/a/b" }),
        20,
        "c1",
      ),
    ).toBe("limit=20&change=granted&change=revoked&library=%2Fa%2Fb&cursor=c1");
    expect(accessLogParams({}, 20, null, 40)).toBe("limit=20&offset=40");
    expect(
      accessLogParams(
        accessLogFilters({ sort: "-change", actor: "alice", subject: "corp:docs" }),
        20,
        null,
        0,
      ),
    ).toBe("limit=20&sort=-change&actor=alice&subject=corp%3Adocs&offset=0");
  });

  it("turns a preset or custom days into the API's time bounds", () => {
    // A preset counts back from the minute, so the loader and the page ask for the same thing.
    expect(whenBounds("24h", Date.parse("2026-11-23T12:00:30Z"))).toEqual({
      at_after: "2026-11-22T12:00:00.000Z",
    });
    // Days run from the start of the first to the start of the day after the last, locally.
    expect(whenBounds("2026-11-01..2026-11-20", 0)).toEqual({
      at_after: new Date(2026, 10, 1).toISOString(),
      at_before: new Date(2026, 10, 21).toISOString(),
    });
    expect(whenBounds("..2026-11-30", 0)).toEqual({
      at_before: new Date(2026, 11, 1).toISOString(),
    });
    expect(whenBounds(undefined, 0)).toEqual({});
  });

  it("explains a refusal", () => {
    expect(explainAccessLogError(new HttpError(403, "/v1/access-log"))).toMatch(/admins/);
    expect(explainAccessLogError(new TypeError("offline"))).toMatch(/Can't reach/);
  });
});

describe("operators' access log", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("lists every library's changes newest first, each with its library and time", async () => {
    stubApi([
      event({ id: "2", change: "library_deleted", kind: null, subject: null, role: null }),
      event({ id: "1", library: "/acme/ledger", role: "admin", previous_role: "viewer" }),
    ]);
    renderAt("all");

    const [first, second] = await rowsOf();
    const one = within(first as HTMLElement);
    const two = within(second as HTMLElement);
    expect(first).toHaveTextContent("alice removed the library and every role on it");
    expect(one.getByRole("link", { name: "/acme/payments" })).toBeInTheDocument();
    expect(one.getByText("Library removed")).toBeInTheDocument();
    expect(one.getByText(/Nov 22/).closest("time")).toHaveAttribute(
      "datetime",
      "2026-11-22T10:00:00Z",
    );
    expect(second).toHaveTextContent("alice changed bob from viewer to admin");
    expect(two.getByRole("link", { name: "/acme/ledger" })).toBeInTheDocument();
    expect(two.getByText("Role changed")).toBeInTheDocument();
    expect(two.getByText("from viewer to admin")).toBeInTheDocument();
    expect(screen.getByText("1–2 of 2")).toBeInTheDocument();
  });

  it("filters by change and by library, in the URL, and sends both to the API", async () => {
    const fetchMock = stubApi([event({ id: "1" }), event({ id: "2", library: "/acme/ledger" })]);
    const history = renderAt("all");
    await rowsOf();

    await userEvent.click(screen.getByRole("button", { name: "Change" }));
    await userEvent.click(
      (await facetOptions()).find((o) => o.textContent === "Roles given or changed") as HTMLElement,
    );
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(asked(fetchMock)).toContain("/api/v1/access-log?limit=20&change=granted&offset=0"),
    );
    expect(history.location.search).toContain("change=granted");

    // The library is picked from the list; a typed text that is no ID is not offered.
    await userEvent.click(screen.getByRole("button", { name: "Library Choose a library…" }));
    const find = screen.getByRole("combobox", { name: "Find a library" });
    await userEvent.type(find, "not-an-id");
    await waitFor(() =>
      expect(
        screen
          .getAllByRole("status")
          .some((s) => s.textContent === "No library matches “not-an-id”."),
      ).toBe(true),
    );
    expect(screen.queryByRole("option", { name: /not-an-id/ })).toBeNull();
    await userEvent.clear(find);
    await userEvent.type(find, "ledger");
    await userEvent.click(await screen.findByRole("option", { name: "/acme/ledger" }));

    await waitFor(() =>
      expect(asked(fetchMock)).toContain(
        "/api/v1/access-log?limit=20&change=granted&library=%2Facme%2Fledger&offset=0",
      ),
    );
    expect(history.location.search).toContain("library=");
    expect(await screen.findByText("1–1 of 1")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Remove filter Library: /acme/ledger" }),
    );
    expect(await screen.findByText("1–2 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Library Choose a library…" })).toBeInTheDocument();
  });

  it("filters by a removed library's typed ID", async () => {
    const fetchMock = stubApi([event({ id: "1", library: "/gone/lib" }), event({ id: "2" })]);
    const history = renderAt("all");
    await rowsOf();
    await userEvent.click(screen.getByRole("button", { name: "Library Choose a library…" }));
    await userEvent.type(screen.getByRole("combobox", { name: "Find a library" }), "/gone/lib");
    await userEvent.click(await screen.findByRole("option", { name: "Use /gone/lib" }));
    await waitFor(() =>
      expect(asked(fetchMock)).toContain(
        "/api/v1/access-log?limit=20&library=%2Fgone%2Flib&offset=0",
      ),
    );
    expect(history.location.search).toContain("library=%2Fgone%2Flib");
    expect(screen.getByRole("button", { name: "Library /gone/lib" })).toBeInTheDocument();
  });

  it("sorts by a header on the server, back to the first page with no cursor", async () => {
    const fetchMock = stubApi(
      Array.from({ length: 25 }, (_, i) =>
        event({ id: `e${i + 1}`, change: i % 2 ? "revoked" : "granted" }),
      ),
    );
    const history = renderAt("all", "?page=2");
    expect(await screen.findByText("21–25 of 25")).toBeInTheDocument();
    // Newest first by default, shown on the When header.
    expect(screen.getByRole("columnheader", { name: /When/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );

    await userEvent.click(screen.getByRole("button", { name: "Sort by Change" }));

    // A cursor belongs to one sort (422 `invalid_cursor` with another): page 1 by offset.
    await waitFor(() =>
      expect(asked(fetchMock)).toContain("/api/v1/access-log?limit=20&sort=change&offset=0"),
    );
    expect(await screen.findByText("1–20 of 25")).toBeInTheDocument();
    expect(history.location.search).toContain("sort=change");
    expect(history.location.search).not.toContain("page=");
    expect(screen.getByRole("columnheader", { name: /Change/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    expect(asked(fetchMock).every((u) => !u.includes("cursor="))).toBe(true);

    await userEvent.click(screen.getByRole("button", { name: "Sort by Library" }));
    await waitFor(() =>
      expect(asked(fetchMock)).toContain("/api/v1/access-log?limit=20&sort=library&offset=0"),
    );
  });

  it("filters by who made a change and whom it was about, as typed", async () => {
    const fetchMock = stubApi([
      event({ id: "1" }),
      event({ id: "2", actor: "carol", subject: "corp:docs", kind: "group" }),
    ]);
    const history = renderAt("all");
    await rowsOf();
    expect(screen.getByLabelText("Changed by")).toHaveAttribute(
      "placeholder",
      "Username or account ID",
    );
    expect(screen.getByLabelText("Person or group")).toHaveAttribute(
      "placeholder",
      "Username, account ID or group name",
    );

    await userEvent.type(screen.getByLabelText("Changed by"), "Carol");
    await waitFor(() =>
      expect(asked(fetchMock)).toContain("/api/v1/access-log?limit=20&actor=Carol&offset=0"),
    );
    expect(await screen.findByText("1–1 of 1")).toBeInTheDocument();
    expect(history.location.search).toContain("actor=Carol");

    await userEvent.type(screen.getByLabelText("Person or group"), "corp:docs");
    await waitFor(() =>
      expect(asked(fetchMock)).toContain(
        "/api/v1/access-log?limit=20&actor=Carol&subject=corp%3Adocs&offset=0",
      ),
    );
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(within(chips).getByText("Carol")).toBeInTheDocument();
    expect(within(chips).getByText("corp:docs")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(await screen.findByText("1–2 of 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Changed by")).toHaveValue("");
    expect(history.location.search).toBe("");
  });

  it("shows one person's or one group's entries from a row's menu", async () => {
    stubApi([
      event({ id: "1" }),
      event({ id: "2", actor: "carol", subject: "corp:docs", kind: "group" }),
    ]);
    const history = renderAt("all");
    await rowsOf();

    await userEvent.click(
      screen.getByRole("button", {
        name: "More actions for carol gave the group corp:docs the viewer role (/acme/payments)",
      }),
    );
    expect(
      await screen.findByRole("menuitem", { name: "Show entries about this group" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("menuitem", { name: "Show this person's entries" }));

    expect(await screen.findByText("1–1 of 1")).toBeInTheDocument();
    expect(history.location.search).toContain("actor=carol");
    expect(screen.getByLabelText("Changed by")).toHaveValue("carol");

    await userEvent.click(
      screen.getByRole("button", {
        name: "More actions for carol gave the group corp:docs the viewer role (/acme/payments)",
      }),
    );
    await userEvent.click(
      await screen.findByRole("menuitem", { name: "Show entries about this group" }),
    );
    await waitFor(() => expect(history.location.search).toContain("subject=corp%3Adocs"));
    expect(screen.getByLabelText("Person or group")).toHaveValue("corp:docs");
  });

  it("filters by a date preset or custom days, in the URL", async () => {
    const fetchMock = stubApi([event({})]);
    const history = renderAt("all");
    await rowsOf();

    await userEvent.click(screen.getByRole("button", { name: "When" }));
    await userEvent.click(
      (await facetOptions()).find((o) => o.textContent === "Last 7 days") as HTMLElement,
    );
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(asked(fetchMock).at(-1)).toMatch(/&at_after=[^&]+&offset=0$/));
    expect(history.location.search).toContain("when=7d");

    await userEvent.click(screen.getByRole("button", { name: "Custom dates" }));
    const form = await screen.findByRole("form", { name: "Changes between two days" });
    // Nothing picked: say so instead of applying nothing.
    fireEvent.change(within(form).getByLabelText("From"), { target: { value: "" } });
    await userEvent.click(within(form).getByRole("button", { name: "Apply" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("Pick a start, an end or both.");
    fireEvent.change(within(form).getByLabelText("From"), { target: { value: "2026-11-20" } });
    fireEvent.change(within(form).getByLabelText("To (included)"), {
      target: { value: "2026-11-01" },
    });
    await userEvent.click(within(form).getByRole("button", { name: "Apply" }));
    expect(within(form).getByRole("alert")).toHaveTextContent(
      "The start must not come after the end.",
    );
    fireEvent.change(within(form).getByLabelText("From"), { target: { value: "2026-11-01" } });
    fireEvent.change(within(form).getByLabelText("To (included)"), {
      target: { value: "2026-11-20" },
    });
    await userEvent.click(within(form).getByRole("button", { name: "Apply" }));

    const after = encodeURIComponent(new Date(2026, 10, 1).toISOString());
    const before = encodeURIComponent(new Date(2026, 10, 21).toISOString());
    await waitFor(() =>
      expect(asked(fetchMock)).toContain(
        `/api/v1/access-log?limit=20&at_after=${after}&at_before=${before}&offset=0`,
      ),
    );
    expect(history.location.search).toContain("when=2026-11-01..2026-11-20");
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(within(chips).getByText("Nov 1, 2026 – Nov 20, 2026")).toBeInTheDocument();
    // The When facet lists the custom days as its pick, so its Clear removes them too.
    await userEvent.click(screen.getByRole("button", { name: "When, 1 selected" }));
    expect((await facetOptions()).map((o) => o.textContent)).toContain(
      "Nov 1, 2026 – Nov 20, 2026",
    );
  });

  it("narrows to one library from a row's menu", async () => {
    stubApi([event({ id: "1" }), event({ id: "2", library: "/acme/ledger" })]);
    const history = renderAt("all");
    await rowsOf();

    await userEvent.click(
      screen.getByRole("button", {
        name: "More actions for alice gave bob the viewer role (/acme/ledger)",
      }),
    );
    expect(await screen.findByRole("menuitem", { name: "Open library" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("menuitem", { name: "Show this library's entries" }));

    expect(await screen.findByText("1–1 of 1")).toBeInTheDocument();
    expect(history.location.search).toContain("library=");
    expect(screen.getByRole("button", { name: "Library /acme/ledger" })).toBeInTheDocument();
  });

  it("pages through a long log by offset, Last in one request", async () => {
    const fetchMock = stubApi(
      Array.from({ length: 25 }, (_, i) => event({ id: `e${i + 1}`, subject: `user${i + 1}` })),
    );
    const history = renderAt("all");
    expect(await screen.findByText("1–20 of 25")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByText("21–25 of 25")).toBeInTheDocument();
    expect(screen.getAllByText("user25")).not.toHaveLength(0);
    expect(history.location.search).toContain("page=2");
    expect(asked(fetchMock)).toContain("/api/v1/access-log?limit=20&offset=20");

    await userEvent.click(screen.getByRole("button", { name: "First page" }));
    expect(await screen.findByText("1–20 of 25")).toBeInTheDocument();
    const before = asked(fetchMock).length;
    await userEvent.click(screen.getByRole("button", { name: "Last page" }));
    expect(await screen.findByText("21–25 of 25")).toBeInTheDocument();
    // Fetched ahead already, or one request by offset; never a cursor walk.
    expect(asked(fetchMock).slice(before).length).toBeLessThanOrEqual(1);
    expect(asked(fetchMock).every((u) => !u.includes("cursor="))).toBe(true);
  });

  it("says so when nothing was recorded", async () => {
    stubApi([]);
    renderAt("all");
    expect(await screen.findByText("Nothing recorded yet")).toBeInTheDocument();
  });
});

describe("a library's access log", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("asks the library's endpoint and links back to its sharing page", async () => {
    const fetchMock = stubApi([event({})]);
    renderAt("library");

    const [first] = await rowsOf();
    expect(first).toHaveTextContent("alice gave bob the viewer role");
    expect(asked(fetchMock)[0]).toBe(
      "/api/v1/libraries/acme/payments/access-log?limit=20&offset=0",
    );
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Sharing" })).toHaveAttribute(
      "href",
      "/libraries/acme/payments/sharing",
    );
    expect(within(crumbs).getByText("Access log")).toHaveAttribute("aria-current", "page");
    expect(screen.queryByLabelText("Library")).not.toBeInTheDocument();
    // One library's events need no library column, and no way to narrow to it.
    expect(screen.queryByRole("columnheader", { name: "Library" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /More actions/ }));
    expect(
      await screen.findByRole("menuitem", { name: "Show this person's entries" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: "Show this library's entries" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Open library" })).not.toBeInTheDocument();
  });

  it("filters one library's log by who and when, and sorts it, in the URL", async () => {
    const fetchMock = stubApi([event({})]);
    const history = renderAt("library", "?actor=alice&when=7d&sort=change");
    await rowsOf();
    const [first] = asked(fetchMock);
    expect(first).toMatch(
      /^\/api\/v1\/libraries\/acme\/payments\/access-log\?limit=20&sort=change&actor=alice&at_after=[^&]+&offset=0$/,
    );
    expect(screen.getByLabelText("Changed by")).toHaveValue("alice");
    expect(screen.queryByRole("button", { name: "Sort by Library" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sort by When" }));
    await waitFor(() => expect(history.location.search).not.toContain("sort=change"));
  });

  it("shows the library's logo in the header when the route knows it", async () => {
    stubApi([event({})]);
    renderAt("library", "", "0123456789abcdef");
    const header = (await screen.findByRole("heading", { level: 1 })).closest("header");
    expect(header?.querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/libraries/acme/payments/logo?v=0123456789abcdef",
    );
  });

  it("tells someone who is no admin of it why they see nothing", async () => {
    stubApi([], 403);
    renderAt("library");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only the library's admins and the server's operators can read its access log.",
    );
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("access log in Polish", () => {
  beforeEach(() => {
    localStorage.clear();
    setPreferences({ language: "pl" });
  });
  afterEach(() => {
    resetPreferences();
    vi.unstubAllGlobals();
  });

  const polish = (e: AccessEvent) =>
    describeEvent(e, "pl")
      .map((p) => p.text)
      .join("");

  it("says who did what with verbs that agree and roles in Polish", () => {
    expect(polish(event({}))).toBe("Użytkownik alice nadał użytkownikowi bob rolę czytelnik");
    expect(polish(event({ role: "contributor", previous_role: "viewer" }))).toBe(
      "Użytkownik alice zmienił użytkownikowi bob rolę z czytelnik na współtwórca",
    );
    expect(polish(event({ change: "revoked", kind: "group", subject: "corp:docs" }))).toBe(
      "Użytkownik alice odebrał rolę czytelnik grupie corp:docs",
    );
    expect(polish(event({ change: "ownership_transferred", subject: "carol" }))).toBe(
      "Użytkownik alice przekazał własność użytkownikowi carol",
    );
    expect(
      polish(
        event({ change: "library_deleted", actor: null, kind: null, subject: null, role: null }),
      ),
    ).toBe(
      "ExactDocs (wiersz poleceń lub zadanie) usunął bibliotekę i wszystkie przypisane do niej role",
    );
    // A role the client does not know shows as the server sent it.
    expect(polish(event({ role: "auditor" }))).toMatch(/rolę auditor$/);
    const parts = describeEvent(
      event({ role: "admin", previous_role: "viewer", kind: "group" }),
      "pl",
    );
    expect(new Set(parts.map((p) => p.key)).size).toBe(parts.length);
  });

  it("renders the operators' log in Polish", async () => {
    stubApi([event({ previous_role: "viewer", role: "admin" })]);
    renderAt("all");
    expect(await screen.findByRole("heading", { name: "Dziennik dostępu" })).toBeInTheDocument();
    const [first] = await rowsOf("Zmiany dostępu, od najnowszych");
    const row = within(first as HTMLElement);
    expect(first).toHaveTextContent(
      "Użytkownik alice zmienił użytkownikowi bob rolę z czytelnik na administrator",
    );
    expect(row.getByText("Zmieniona rola")).toBeInTheDocument();
    expect(row.getByText("z czytelnik na administrator")).toBeInTheDocument();
    expect(row.getByText(/22 lis/).closest("time")).toHaveAttribute(
      "datetime",
      "2026-11-22T10:00:00Z",
    );
    expect(screen.getByText("1–1 z 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Zmiana" }));
    expect((await facetOptions()).map((o) => o.textContent)).toContain("Usunięcia bibliotek");
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Biblioteka Wybierz bibliotekę…" }));
    await userEvent.type(
      screen.getByRole("combobox", { name: "Znajdź bibliotekę" }),
      "/usunieta/biblioteka",
    );
    expect(
      await screen.findByRole("option", { name: "Użyj /usunieta/biblioteka" }),
    ).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.getByLabelText("Autor zmiany")).toHaveAttribute(
      "placeholder",
      "Nazwa użytkownika lub ID konta",
    );
    expect(screen.getByLabelText("Osoba lub grupa")).toHaveAttribute(
      "placeholder",
      "Nazwa użytkownika, ID konta lub nazwa grupy",
    );
    expect(screen.getByRole("button", { name: "Sortuj według: Zmiana" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Kiedy" }));
    expect((await facetOptions()).map((o) => o.textContent)).toContain("Ostatnie 7 dni");
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Wybrane dni" }));
    const form = await screen.findByRole("form", { name: "Zmiany z wybranych dni" });
    fireEvent.change(within(form).getByLabelText("Od"), { target: { value: "2026-11-01" } });
    await userEvent.click(within(form).getByRole("button", { name: "Zastosuj" }));
    const chips = await screen.findByRole("list", { name: "Aktywne filtry" });
    expect(within(chips).getByText("Od 1 lis 2026")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Więcej opcji/ }));
    expect(
      await screen.findByRole("menuitem", { name: "Pokaż zmiany wprowadzone przez tę osobę" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Pokaż wpisy dotyczące tej osoby" }),
    ).toBeInTheDocument();
  });

  it("explains a refusal in Polish", async () => {
    stubApi([], 403);
    renderAt("library");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Dziennik dostępu biblioteki mogą przeglądać tylko jej administratorzy i operatorzy serwera.",
    );
    expect(screen.getByRole("link", { name: "Udostępnianie" })).toBeInTheDocument();
    expect(document.title).toBe("Dziennik dostępu /acme/payments - ExactDocs");
  });
});
