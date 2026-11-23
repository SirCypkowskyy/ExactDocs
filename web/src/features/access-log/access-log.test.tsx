import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
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
 * An access log API over `events` that filters by `change` (repeatable) and `library`, and pages
 * with `limit` and an offset cursor (`o<n>`); or one that refuses with `status`.
 */
function stubApi(events: AccessEvent[], status = 200) {
  const fetchMock = vi.fn(async (url: string) => {
    if (status !== 200) return json({ error: "forbidden", detail: "no", fields: [] }, status);
    const params = new URL(url, "http://x").searchParams;
    const changes = params.getAll("change");
    const library = params.get("library");
    const shown = events.filter(
      (e) =>
        (changes.length === 0 || changes.includes(e.change)) && (!library || e.library === library),
    );
    const start = Number(params.get("cursor")?.slice(1) ?? 0);
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
function renderAt(page: "all" | "library", search = "") {
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
              <LibraryAccessLogPage owner="acme" repo="payments" />
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
      }),
    ).toEqual({
      change: ["granted", "revoked"],
      library: "/acme/payments",
      page: 2,
      size: 50,
    });
    expect(parseAccessLogView({ change: "nuked", library: "acme", size: 7 })).toEqual({
      change: undefined,
      library: undefined,
      page: undefined,
      size: undefined,
    });
    expect(parseLibraryAccessLogView({ change: "granted", library: "/acme/payments" })).toEqual({
      change: ["granted"],
      page: undefined,
      size: undefined,
    });
    expect(
      accessLogParams(
        accessLogFilters({ change: ["granted", "revoked"], library: "/a/b" }),
        20,
        "c1",
      ),
    ).toBe("limit=20&change=granted&change=revoked&library=%2Fa%2Fb&cursor=c1");
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
      expect(asked(fetchMock)).toContain("/api/v1/access-log?limit=20&change=granted"),
    );
    expect(history.location.search).toContain("change=granted");

    await userEvent.type(screen.getByLabelText("Library"), "not-an-id");
    expect(screen.getByText("Write the library's ID as /owner/repo.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Library"));
    await userEvent.type(screen.getByLabelText("Library"), "/acme/ledger{Enter}");

    await waitFor(() =>
      expect(asked(fetchMock)).toContain(
        "/api/v1/access-log?limit=20&change=granted&library=%2Facme%2Fledger",
      ),
    );
    expect(history.location.search).toContain("library=");
    expect(await screen.findByText("1–1 of 1")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Remove filter Library: /acme/ledger" }),
    );
    expect(await screen.findByText("1–2 of 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Library")).toHaveValue("");
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
    expect(screen.getByLabelText("Library")).toHaveValue("/acme/ledger");
  });

  it("pages through a long log, the next page asked for with the first one's cursor", async () => {
    const fetchMock = stubApi(
      Array.from({ length: 25 }, (_, i) => event({ id: `e${i + 1}`, subject: `user${i + 1}` })),
    );
    const history = renderAt("all");
    expect(await screen.findByText("1–20 of 25")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByText("21–25 of 25")).toBeInTheDocument();
    expect(screen.getAllByText("user25")).not.toHaveLength(0);
    expect(history.location.search).toContain("page=2");
    expect(asked(fetchMock)).toContain("/api/v1/access-log?limit=20&cursor=o20");
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
    expect(asked(fetchMock)[0]).toBe("/api/v1/libraries/acme/payments/access-log?limit=20");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Sharing" })).toHaveAttribute(
      "href",
      "/libraries/acme/payments/sharing",
    );
    expect(within(crumbs).getByText("Access log")).toHaveAttribute("aria-current", "page");
    expect(screen.queryByLabelText("Library")).not.toBeInTheDocument();
    // One library's events need no library column, and no way to narrow to it.
    expect(screen.queryByRole("columnheader", { name: "Library" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /More actions/ })).not.toBeInTheDocument();
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
    await userEvent.type(screen.getByLabelText("Biblioteka"), "nie-id");
    expect(
      screen.getByText("Wpisz identyfikator biblioteki w postaci /owner/repo."),
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
