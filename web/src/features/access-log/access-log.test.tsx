import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { AccessLogPage, LibraryAccessLogPage, parseAccessLogView } from "./index";
import { type AccessEvent, describeEvent, explainAccessLogError } from "./model/access-log";

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

function stubApi(events: AccessEvent[], status = 200) {
  const fetchMock = vi.fn(async (url: string) => {
    if (status !== 200) return json({ error: "forbidden", detail: "no", fields: [] }, status);
    const change = new URL(url, "http://x").searchParams.get("change");
    const shown = events.filter((e) => !change || e.change === change);
    return json({ events: shown, next_cursor: null, total: shown.length });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function withClient(children: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

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
    expect(parseAccessLogView({ change: "granted", library: "/acme/payments" })).toEqual({
      change: "granted",
      library: "/acme/payments",
    });
    expect(parseAccessLogView({ change: "nuked", library: "acme" })).toEqual({
      change: undefined,
      library: undefined,
    });
  });

  it("explains a refusal", () => {
    expect(explainAccessLogError(new HttpError(403, "/v1/access-log"))).toMatch(/admins/);
    expect(explainAccessLogError(new TypeError("offline"))).toMatch(/Can't reach/);
  });
});

describe("operators' access log", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists every library's changes newest first, each with its library and time", async () => {
    stubApi([
      event({ id: "2", change: "library_deleted", kind: null, subject: null, role: null }),
      event({ id: "1", library: "/acme/ledger" }),
    ]);
    render(withClient(<AccessLogPage />));

    const list = await screen.findByRole("list", { name: "Access changes, newest first" });
    const [first, second] = within(list).getAllByRole("listitem");
    expect(first).toHaveTextContent("alice removed the library and every role on it");
    expect(first).toHaveTextContent("/acme/payments");
    expect(second).toHaveTextContent("alice gave bob the viewer role");
    expect(second).toHaveTextContent("/acme/ledger");
    expect(within(first as HTMLElement).getByText(/Nov 22/)).toHaveAttribute(
      "datetime",
      "2026-11-22T10:00:00Z",
    );
    expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();
  });

  it("filters by change and by library through the view", async () => {
    stubApi([event({})]);
    const onView = vi.fn();
    render(withClient(<AccessLogPage onView={onView} />));

    await userEvent.selectOptions(await screen.findByLabelText("Show"), "library_deleted");
    expect(onView).toHaveBeenLastCalledWith({ change: "library_deleted" });

    await userEvent.type(screen.getByLabelText("Library"), "not-an-id");
    expect(screen.getByText("Write the library's ID as /owner/repo.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Library"));
    await userEvent.type(screen.getByLabelText("Library"), "/acme/ledger{Enter}");
    expect(onView).toHaveBeenLastCalledWith({ library: "/acme/ledger" });
  });

  it("says so when nothing was recorded", async () => {
    stubApi([]);
    render(withClient(<AccessLogPage />));
    expect(await screen.findByText("Nothing recorded yet")).toBeInTheDocument();
  });
});

describe("a library's access log", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks the library's endpoint and links back to its sharing page", async () => {
    const fetchMock = stubApi([event({})]);
    render(
      withClient(
        <TestRouter pages={{ "/": () => <LibraryAccessLogPage owner="acme" repo="payments" /> }} />,
      ),
    );

    expect(
      await screen.findByRole("list", { name: "Access changes, newest first" }),
    ).toHaveTextContent("alice gave bob the viewer role");
    expect(String(fetchMock.mock.calls[0]?.[0])).toMatch(
      /^\/api\/v1\/libraries\/acme\/payments\/access-log\?/,
    );
    expect(screen.getByRole("link", { name: "Sharing" })).toHaveAttribute(
      "href",
      "/libraries/acme/payments/sharing",
    );
    expect(screen.queryByLabelText("Library")).not.toBeInTheDocument();
  });

  it("tells someone who is no admin of it why they see nothing", async () => {
    stubApi([], 403);
    render(
      withClient(
        <TestRouter pages={{ "/": () => <LibraryAccessLogPage owner="acme" repo="payments" /> }} />,
      ),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only the library's admins and the server's operators can read its access log.",
    );
  });
});

describe("access log in Polish", () => {
  beforeEach(() => setPreferences({ language: "pl" }));
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
    stubApi([event({})]);
    render(withClient(<AccessLogPage />));
    expect(await screen.findByRole("heading", { name: "Dziennik dostępu" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Zmiany dostępu, od najnowszych" });
    expect(list).toHaveTextContent("Użytkownik alice nadał użytkownikowi bob rolę czytelnik");
    expect(within(list).getByText(/22 lis/)).toHaveAttribute("datetime", "2026-11-22T10:00:00Z");
    expect(screen.getByText("Wyświetlono 1 z 1")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Usunięcia bibliotek" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Biblioteka"), "nie-id");
    expect(
      screen.getByText("Wpisz identyfikator biblioteki w postaci /owner/repo."),
    ).toBeInTheDocument();
  });

  it("explains a refusal in Polish", async () => {
    stubApi([], 403);
    render(
      withClient(
        <TestRouter pages={{ "/": () => <LibraryAccessLogPage owner="acme" repo="payments" /> }} />,
      ),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Dziennik dostępu biblioteki mogą przeglądać tylko jej administratorzy i operatorzy serwera.",
    );
    expect(screen.getByRole("link", { name: "Udostępnianie" })).toBeInTheDocument();
    expect(document.title).toBe("Dziennik dostępu /acme/payments - ExactDocs");
  });
});
