import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { SharingPage } from "./index";
import { canManage, explainSharingError, givableRoles } from "./model/grant";
import { grantsFilters, grantsParams, parseSharingView } from "./model/grants-view";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const BASE = "/api/v1/libraries/acme/payments";
type Row = { kind: "user" | "group"; subject: string; role: string };
const json = (body: unknown, status = 200) => Response.json(body, { status });
const refuse = (status: number, error: string, detail = error) =>
  json({ error, detail, fields: [] }, status);

/**
 * A tiny in-memory sharing API for one library, called as `me`: the creator holds `creator`,
 * anyone else here is an admin (an operator would be `creator` too). It filters by `kind` and
 * `role` (repeatable) and `q`, and pages with `limit` and an offset cursor (`o<n>`).
 */
function stubApi(me: string, rows: Row[] = defaultRows()) {
  let grants = [...rows];
  const callerRole = () =>
    grants.some((g) => g.kind === "user" && g.subject === me && g.role === "creator")
      ? "creator"
      : "admin";
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url.startsWith(`${BASE}/grants?`) && method === "GET") {
      const params = new URL(url, "http://localhost").searchParams;
      const roles = params.getAll("role");
      const kinds = params.getAll("kind");
      const q = params.get("q") ?? "";
      const shown = grants.filter(
        (g) =>
          (roles.length === 0 || roles.includes(g.role)) &&
          (kinds.length === 0 || kinds.includes(g.kind)) &&
          g.subject.includes(q),
      );
      const start = Number(params.get("cursor")?.slice(1) ?? 0);
      const limit = Number(params.get("limit"));
      return json({
        grants: shown.slice(start, start + limit),
        next_cursor: start + limit < shown.length ? `o${start + limit}` : null,
        total: shown.length,
        caller_role: callerRole(),
        creator: grants.find((g) => g.role === "creator")?.subject ?? null,
      });
    }
    if (url === `${BASE}/grants` && method === "PUT") {
      const body = JSON.parse(String(init?.body)) as Row;
      if (body.kind === "user" && body.subject === "zed") return refuse(404, "unknown_account");
      grants = [...grants.filter((g) => g.kind !== body.kind || g.subject !== body.subject), body];
      return json({ grants });
    }
    const removed = url.match(/\/grants\/(user|group)\/(.+)$/);
    if (removed && method === "DELETE") {
      const [, kind, subject] = removed;
      const held = grants.find(
        (g) => g.kind === kind && g.subject === decodeURIComponent(subject ?? ""),
      );
      if (held?.role === "admin" && callerRole() !== "creator") {
        return refuse(403, "forbidden", "this needs the creator role on the library");
      }
      grants = grants.filter((g) => g !== held);
      return json({ grants });
    }
    if (url === `${BASE}/transfer` && method === "POST") {
      const { username } = JSON.parse(String(init?.body)) as { username: string };
      if (callerRole() !== "creator") return refuse(403, "forbidden", "needs the creator role");
      if (username === "zed") return refuse(404, "unknown_account");
      grants = grants
        .filter((g) => g.kind !== "user" || g.subject !== username)
        .map((g) => (g.role === "creator" ? { ...g, role: "admin" } : g));
      grants = [...grants, { kind: "user", subject: username, role: "creator" }];
      return json({ grants });
    }
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function defaultRows(): Row[] {
  return [
    { kind: "user", subject: "alice", role: "creator" },
    { kind: "user", subject: "bob", role: "admin" },
    { kind: "user", subject: "dave", role: "viewer" },
    { kind: "group", subject: "corp:docs", role: "contributor" },
  ];
}

const PATH = "/libraries/acme/payments/sharing";

/** The page under a memory router, so the table's view lives in the URL as in the app. */
function renderPage(search = "") {
  const history = createMemoryHistory({ initialEntries: [`${PATH}${search}`] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TestRouter
          history={history}
          pages={{
            "/": () => <p>Libraries home</p>,
            "/libraries/$owner/$repo": () => <p>Browse</p>,
            "/libraries/$owner/$repo/sharing": () => (
              <SharingPage
                owner="acme"
                repo="payments"
                libraryId="/acme/payments"
                title="Payments"
              />
            ),
          }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

const sent = (fetchMock: ReturnType<typeof stubApi>, method: string) =>
  fetchMock.mock.calls
    .filter(([, init]) => init?.method === method)
    .map(([url, init]) => [String(url), init?.body ? JSON.parse(String(init.body)) : undefined]);

const listed = (fetchMock: ReturnType<typeof stubApi>) =>
  fetchMock.mock.calls
    .map(([url]) => String(url))
    .filter((u) => u.startsWith(`${BASE}/grants?`) && u !== `${BASE}/grants?limit=1`);

/** The table once its rows are in (its skeleton rows come first). */
async function rows(label = "Who has access") {
  const table = await screen.findByRole("table", { name: label });
  await within(table).findByText("corp:docs");
  return table;
}

/** A faceted filter's options (the role selects in the rows are options too). */
const facetOptions = async () => within(await screen.findByRole("listbox")).getAllByRole("option");

const row = (name: string) => {
  const cell = within(screen.getByRole("table", { name: "Who has access" })).getByText(name);
  const tr = cell.closest("tr");
  if (!tr) throw new Error(`no row for ${name}`);
  return within(tr);
};

describe("the sharing view", () => {
  it("keeps only what the API knows from a hand-edited URL", () => {
    expect(
      parseSharingView({
        q: " bo ",
        kind: "group",
        role: "admin,viewer",
        sort: "-role",
        page: 2,
        size: 50,
      }),
    ).toEqual({
      q: "bo",
      kind: ["group"],
      role: ["viewer", "admin"],
      sort: "-role",
      page: 2,
      size: 50,
    });
    expect(parseSharingView({ kind: "team", role: "owner", sort: "created_at", size: 7 })).toEqual({
      q: undefined,
      kind: undefined,
      role: undefined,
      sort: undefined,
      page: undefined,
      size: undefined,
    });
    expect(
      grantsParams(
        grantsFilters({ q: "b", kind: ["user"], role: ["viewer", "admin"], sort: "subject" }),
        20,
        "c1",
      ),
    ).toBe("limit=20&q=b&kind=user&role=viewer&role=admin&sort=subject&cursor=c1");
  });

  it("lets only the creator give, change or take away admin", () => {
    const admin = { kind: "user" as const, subject: "bob", role: "admin" };
    const creator = { kind: "user" as const, subject: "alice", role: "creator" };
    expect(givableRoles("admin")).toEqual(["viewer", "contributor"]);
    expect(givableRoles("creator")).toEqual(["viewer", "contributor", "admin"]);
    expect(canManage(admin, "admin")).toBe(false);
    expect(canManage(admin, "creator")).toBe(true);
    expect(canManage(creator, "creator")).toBe(false);
  });

  it("explains every refusal in a sentence", () => {
    const err = (status: number, error: string, detail = error) =>
      new HttpError(status, "/v1/x", { error, detail, fields: [] });
    expect(explainSharingError(err(403, "forbidden", "this needs the creator role"))).toMatch(
      /Only the library's creator/,
    );
    expect(explainSharingError(err(403, "forbidden", "this needs the admin role"))).toMatch(
      /Only an admin of this library/,
    );
    expect(explainSharingError(err(404, "unknown_account"))).toMatch(/No account has that/);
    expect(explainSharingError(err(422, "invalid_grant", "bob is already the creator"))).toMatch(
      /already the creator/,
    );
    expect(explainSharingError(new TypeError("offline"))).toMatch(/Can't reach the server/);
  });
});

describe("sharing page", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("shows the creator, the roles, and lets the creator change and remove an admin", async () => {
    const fetchMock = stubApi("alice");
    renderPage();

    expect(await screen.findByText("Created by", { exact: false })).toHaveTextContent(
      "Created by alice",
    );
    await rows();
    expect(row("alice").queryByRole("combobox")).not.toBeInTheDocument();
    expect(row("alice").getByText("Creator")).toBeInTheDocument();
    expect(row("corp:docs").getByText("Group")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transfer ownership" })).toBeInTheDocument();

    await userEvent.selectOptions(
      row("bob").getByRole("combobox", { name: "Role of bob" }),
      "viewer",
    );
    await waitFor(() =>
      expect(sent(fetchMock, "PUT")).toEqual([
        [`${BASE}/grants`, { kind: "user", subject: "bob", role: "viewer" }],
      ]),
    );

    await userEvent.click(row("dave").getByRole("button", { name: "More actions for dave" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Remove…" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Remove dave?" });
    expect(dialog).toHaveTextContent("dave loses the viewer role");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(screen.queryByText("dave")).not.toBeInTheDocument());
    expect(sent(fetchMock, "DELETE")).toEqual([[`${BASE}/grants/user/dave`, undefined]]);
    // The row is gone: focus lands on the page's heading, not on the page's end.
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Sharing" })).toHaveFocus(),
    );
  });

  it("offers the other roles and removal in a row's menu, mirrored in its context menu", async () => {
    const fetchMock = stubApi("alice");
    renderPage();
    await rows();

    await userEvent.click(row("dave").getByRole("button", { name: "More actions for dave" }));
    const menu = await screen.findByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((item) => item.textContent),
    ).toEqual(["Change role to contributor", "Change role to admin", "Remove…"]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Change role to admin" }));
    await waitFor(() =>
      expect(sent(fetchMock, "PUT")).toEqual([
        [`${BASE}/grants`, { kind: "user", subject: "dave", role: "admin" }],
      ]),
    );

    // The creator's own row hands the library over, from the keyboard too.
    row("alice").getByText("alice").closest("tr")?.focus();
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const context = await screen.findByRole("menu");
    await userEvent.click(within(context).getByRole("menuitem", { name: "Transfer ownership…" }));
    expect(await screen.findByRole("dialog", { name: "Transfer /acme/payments" })).toBeVisible();
  });

  it("gives an admin no way to touch admins, nor to transfer", async () => {
    stubApi("bob");
    renderPage();

    await rows();
    expect(row("bob").queryByRole("combobox")).not.toBeInTheDocument();
    expect(row("bob").queryByRole("button", { name: /More actions/ })).not.toBeInTheDocument();
    expect(row("alice").queryByRole("button", { name: /More actions/ })).not.toBeInTheDocument();
    expect(row("dave").getByRole("combobox", { name: "Role of dave" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Transfer ownership" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Access log" })).toHaveAttribute(
      "href",
      "/libraries/acme/payments/access-log",
    );
    await userEvent.click(row("dave").getByRole("button", { name: "More actions for dave" }));
    expect((await screen.findAllByRole("menuitem")).map((item) => item.textContent)).toEqual([
      "Change role to contributor",
      "Remove…",
    ]);
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByRole("button", { name: "Share" }));
    const dialog = await screen.findByRole("dialog");
    const roles = within(dialog).getByRole("combobox", { name: "Role" });
    expect(
      within(roles)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Viewer", "Contributor"]);
    expect(dialog).toHaveTextContent("Only the library's creator makes someone an admin.");
  });

  it("links back through one breadcrumb", async () => {
    stubApi("alice");
    renderPage();
    const crumbs = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Libraries" })).toHaveAttribute("href", "/");
    expect(within(crumbs).getByRole("link", { name: "/acme/payments" })).toHaveAttribute(
      "href",
      "/libraries/acme/payments",
    );
    expect(within(crumbs).getByText("Sharing")).toHaveAttribute("aria-current", "page");
  });

  it("shares with a group, and names an unknown username on its field", async () => {
    const fetchMock = stubApi("alice");
    renderPage();
    await rows();

    await userEvent.click(screen.getByRole("button", { name: "Share" }));
    let dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Username"), "zed");
    await userEvent.click(within(dialog).getByRole("button", { name: "Share" }));
    expect(await within(dialog).findByText(/No account has that username/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Username")).toHaveAttribute("aria-invalid", "true");

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Share" }));
    dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("radio", { name: "A group" }));
    await userEvent.type(within(dialog).getByLabelText("Group"), "corp:payments");
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Role" }), "admin");
    await userEvent.click(within(dialog).getByRole("button", { name: "Share" }));

    expect(await screen.findByText("corp:payments")).toBeInTheDocument();
    expect(sent(fetchMock, "PUT").at(-1)).toEqual([
      `${BASE}/grants`,
      { kind: "group", subject: "corp:payments", role: "admin" },
    ]);
  });

  it("transfers ownership: the new user is the creator, the creator before an admin", async () => {
    const fetchMock = stubApi("alice");
    renderPage();
    await rows();

    await userEvent.click(screen.getByRole("button", { name: "Transfer ownership" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("New creator's username"), "carol");
    await userEvent.click(within(dialog).getByRole("button", { name: "Transfer ownership" }));

    expect(await screen.findByText("Created by", { exact: false })).toHaveTextContent(
      "Created by carol",
    );
    expect(sent(fetchMock, "POST")).toEqual([[`${BASE}/transfer`, { username: "carol" }]]);
    await waitFor(() => expect(row("carol").getByText("Creator")).toBeInTheDocument());
    // alice is an admin now: she sees her own admin row read-only and can no longer transfer.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Transfer ownership" })).not.toBeInTheDocument(),
    );
    expect(row("alice").getByText("Admin")).toBeInTheDocument();
  });

  it("asks the server to sort and filter, keeps the view in the URL and clears it", async () => {
    const fetchMock = stubApi("alice");
    const history = renderPage();
    const table = await rows();
    // The API's own order (users, then groups) shows on the Kind column.
    expect(within(table).getByRole("columnheader", { name: /Kind/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );

    await userEvent.click(screen.getByRole("button", { name: "Sort by Role" }));
    await waitFor(() => expect(listed(fetchMock)).toContain(`${BASE}/grants?limit=20&sort=-role`));
    expect(history.location.search).toContain("sort=-role");

    await userEvent.click(screen.getByRole("button", { name: "Kind" }));
    await userEvent.click(
      (await facetOptions()).find((o) => o.textContent === "Groups") as HTMLElement,
    );
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(listed(fetchMock)).toContain(`${BASE}/grants?limit=20&kind=group&sort=-role`),
    );
    expect(history.location.search).toContain("kind=group");
    expect(await screen.findByText("1–1 of 1")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Role" }));
    await userEvent.click(
      (await facetOptions()).find((o) => o.textContent === "Viewer") as HTMLElement,
    );
    await userEvent.keyboard("{Escape}");
    expect(await screen.findByText("Nobody matches.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("1–4 of 4")).toBeInTheDocument();
    expect(history.location.search).toBe("?sort=-role");
  });

  it("pages through many grants, the next page asked for with the first one's cursor", async () => {
    const people: Row[] = Array.from({ length: 24 }, (_, i) => ({
      kind: "user",
      subject: `user${String(i + 1).padStart(2, "0")}`,
      role: "viewer",
    }));
    const fetchMock = stubApi("alice", [
      { kind: "user", subject: "alice", role: "creator" },
      ...people,
    ]);
    const history = renderPage();
    expect(await screen.findByText("1–20 of 25")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByText("21–25 of 25")).toBeInTheDocument();
    expect(row("user24").getByRole("combobox", { name: "Role of user24" })).toBeInTheDocument();
    expect(history.location.search).toContain("page=2");
    expect(listed(fetchMock)).toContain(`${BASE}/grants?limit=20&cursor=o20`);
  });

  it("tells someone who isn't an admin of the library that they can't manage it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => refuse(403, "forbidden", "this needs the admin role on the library")),
    );
    renderPage();

    expect(
      await screen.findByText("Only the library's admins manage its sharing"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Share" })).not.toBeInTheDocument();
  });

  it("invites a first share when nobody has access yet", async () => {
    stubApi("alice", []);
    renderPage();
    expect(await screen.findByText("Not shared with anyone yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("sharing page in Polish", () => {
  beforeEach(() => {
    localStorage.clear();
    setPreferences({ language: "pl" });
  });
  afterEach(() => {
    resetPreferences();
    vi.unstubAllGlobals();
  });

  const rowPl = (name: string) => {
    const cell = within(screen.getByRole("table", { name: "Kto ma dostęp" })).getByText(name);
    return within(cell.closest("tr") as HTMLElement);
  };

  it("names roles, actions and outcomes in Polish", async () => {
    stubApi("alice");
    renderPage();

    expect(await screen.findByRole("heading", { level: 1, name: "Udostępnianie" })).toBeVisible();
    expect(await screen.findByText(/Twórca:/)).toHaveTextContent(
      "Twórca: alice. Tylko twórca nadaje i odbiera rolę administratora oraz może przekazać bibliotekę.",
    );
    await rows("Kto ma dostęp");
    expect(rowPl("alice").getByText("Twórca")).toBeInTheDocument();
    expect(rowPl("corp:docs").getByText("Grupa")).toBeInTheDocument();
    expect(rowPl("bob").getByRole("combobox", { name: "Rola: bob" })).toHaveValue("admin");
    expect(screen.getByRole("button", { name: "Przekaż własność" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dziennik dostępu" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Rodzaj" }));
    expect((await facetOptions()).map((o) => o.textContent)).toEqual(["Użytkownicy", "Grupy"]);
    await userEvent.keyboard("{Escape}");

    await userEvent.click(rowPl("dave").getByRole("button", { name: "Więcej opcji: dave" }));
    expect((await screen.findAllByRole("menuitem")).map((item) => item.textContent)).toEqual([
      "Zmień rolę na: współtwórca",
      "Zmień rolę na: administrator",
      "Usuń…",
    ]);
    await userEvent.click(screen.getByRole("menuitem", { name: "Usuń…" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent(
      "Usunąć dostęp użytkownika dave?",
    );
    expect(dialog).toHaveTextContent("dave traci rolę czytelnika. Dostęp kończy się natychmiast");
    await userEvent.click(within(dialog).getByRole("button", { name: "Usuń" }));
    await waitFor(() =>
      expect(
        screen.getByText("dave nie ma już dostępu.", { selector: "[role=status]" }),
      ).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: "Udostępnij" }));
    const share = await screen.findByRole("dialog");
    expect(within(share).getByRole("heading")).toHaveTextContent("Udostępnij /acme/payments");
    const roles = within(share).getByRole("combobox", { name: "Rola" });
    expect(
      within(roles)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Czytelnik", "Współtwórca", "Administrator"]);
    await userEvent.click(within(share).getByRole("button", { name: "Udostępnij" }));
    expect(await within(share).findByText("Wpisz nazwę użytkownika.")).toBeInTheDocument();
    await userEvent.click(within(share).getByRole("radio", { name: "Grupie" }));
    expect(within(share).getByLabelText("Grupa")).toBeInTheDocument();
  });

  it("explains a refusal in Polish", () => {
    const refused = new HttpError(404, "/v1/x", {
      error: "unknown_account",
      detail: "unknown_account",
      fields: [],
    });
    expect(explainSharingError(refused, "pl")).toBe(
      "Żadne konto nie ma takiej nazwy użytkownika. Sprawdź pisownię lub poproś operatora o utworzenie konta.",
    );
    expect(explainSharingError(new TypeError("offline"), "pl")).toMatch(/Nie można połączyć się/);
  });
});
