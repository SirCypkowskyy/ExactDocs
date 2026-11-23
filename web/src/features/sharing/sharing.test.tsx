import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { SharingPage } from "./index";
import { canManage, explainSharingError, givableRoles } from "./model/grant";
import { grantsParams, parseSharingView, type SharingView } from "./model/grants-view";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const BASE = "/api/v1/libraries/acme/payments";
type Row = { kind: "user" | "group"; subject: string; role: string };
const json = (body: unknown, status = 200) => Response.json(body, { status });
const refuse = (status: number, error: string, detail = error) =>
  json({ error, detail, fields: [] }, status);

/**
 * A tiny in-memory sharing API for one library, called as `me`: the creator holds `creator`,
 * anyone else here is an admin (an operator would be `creator` too).
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
      const shown = grants.filter(
        (g) =>
          (!params.get("role") || g.role === params.get("role")) &&
          (!params.get("kind") || g.kind === params.get("kind")),
      );
      return json({
        grants: shown,
        next_cursor: null,
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

/** The route keeps the view in the URL; here a state stands in for it. */
function Harness({ seen }: { seen: SharingView[] }) {
  const [view, setView] = useState<SharingView>({});
  return (
    <SharingPage
      owner="acme"
      repo="payments"
      libraryId="/acme/payments"
      title="Payments"
      view={view}
      onView={(next) => {
        seen.push(next);
        setView(next);
      }}
    />
  );
}

function renderPage() {
  const seen: SharingView[] = [];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TestRouter
        pages={{
          "/": () => <p>Libraries home</p>,
          "/libraries/$owner/$repo": () => <p>Browse</p>,
          "/libraries/$owner/$repo/sharing": () => <Harness seen={seen} />,
        }}
        start="/libraries/acme/payments/sharing"
      />
    </QueryClientProvider>,
  );
  return seen;
}

const sent = (fetchMock: ReturnType<typeof stubApi>, method: string) =>
  fetchMock.mock.calls
    .filter(([, init]) => init?.method === method)
    .map(([url, init]) => [String(url), init?.body ? JSON.parse(String(init.body)) : undefined]);

const row = (name: string) => {
  const cell = within(screen.getByRole("table", { name: "Who has access" })).getByText(name);
  const tr = cell.closest("tr");
  if (!tr) throw new Error(`no row for ${name}`);
  return within(tr);
};

describe("the sharing view", () => {
  it("keeps only what the API knows from a hand-edited URL", () => {
    expect(parseSharingView({ q: " bo ", kind: "group", role: "admin", sort: "-role" })).toEqual({
      q: "bo",
      kind: "group",
      role: "admin",
      sort: "-role",
    });
    expect(parseSharingView({ kind: "team", role: "owner", sort: "created_at" })).toEqual({
      q: undefined,
      kind: undefined,
      role: undefined,
      sort: undefined,
    });
    expect(grantsParams({ q: "b", kind: "user", role: "viewer", sort: "subject" }, "c1")).toBe(
      "limit=50&q=b&kind=user&role=viewer&sort=subject&cursor=c1",
    );
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
  afterEach(() => vi.unstubAllGlobals());

  it("shows the creator, the roles, and lets the creator change and remove an admin", async () => {
    const fetchMock = stubApi("alice");
    renderPage();

    expect(await screen.findByText("Created by", { exact: false })).toHaveTextContent(
      "Created by alice",
    );
    expect(row("alice").queryByRole("combobox")).not.toBeInTheDocument();
    expect(row("alice").getByText("Creator")).toBeInTheDocument();
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

    await userEvent.click(row("dave").getByRole("button", { name: "Remove dave" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("dave loses the viewer role");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(screen.queryByText("dave")).not.toBeInTheDocument());
    expect(sent(fetchMock, "DELETE")).toEqual([[`${BASE}/grants/user/dave`, undefined]]);
  });

  it("gives an admin no way to touch admins, nor to transfer", async () => {
    stubApi("bob");
    renderPage();

    await screen.findByRole("table", { name: "Who has access" });
    expect(row("bob").queryByRole("combobox")).not.toBeInTheDocument();
    expect(row("bob").queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
    expect(row("dave").getByRole("combobox", { name: "Role of dave" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Transfer ownership" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Access log" })).toHaveAttribute(
      "href",
      "/libraries/acme/payments/access-log",
    );

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

  it("shares with a group, and names an unknown username on its field", async () => {
    const fetchMock = stubApi("alice");
    renderPage();
    await screen.findByRole("table", { name: "Who has access" });

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
    await screen.findByRole("table", { name: "Who has access" });

    await userEvent.click(screen.getByRole("button", { name: "Transfer ownership" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("New creator's username"), "carol");
    await userEvent.click(within(dialog).getByRole("button", { name: "Transfer ownership" }));

    expect(await screen.findByText("Created by", { exact: false })).toHaveTextContent(
      "Created by carol",
    );
    expect(sent(fetchMock, "POST")).toEqual([[`${BASE}/transfer`, { username: "carol" }]]);
    expect(row("carol").getByText("Creator")).toBeInTheDocument();
    // alice is an admin now: she sees her own admin row read-only and can no longer transfer.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Transfer ownership" })).not.toBeInTheDocument(),
    );
    expect(row("alice").getByText("Admin")).toBeInTheDocument();
  });

  it("asks the server to sort and filter, and offers to clear filters", async () => {
    const fetchMock = stubApi("alice");
    const seen = renderPage();
    await screen.findByRole("table", { name: "Who has access" });

    await userEvent.click(screen.getByRole("button", { name: "Sort by Role" }));
    expect(seen.at(-1)).toEqual({ sort: "-role" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Kind" }), "group");
    expect(seen.at(-1)).toEqual({ sort: "-role", kind: "group" });
    await waitFor(() =>
      expect(fetchMock.mock.calls.map(([u]) => String(u))).toContain(
        `${BASE}/grants?limit=50&kind=group&sort=-role`,
      ),
    );
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Role" }), "viewer");

    await userEvent.click(await screen.findByRole("button", { name: "Clear filters" }));
    expect(seen.at(-1)).toEqual({ sort: "-role" });
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
});

describe("sharing page in Polish", () => {
  beforeEach(() => setPreferences({ language: "pl" }));
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
    expect(rowPl("alice").getByText("Twórca")).toBeInTheDocument();
    expect(rowPl("bob").getByRole("combobox", { name: "Rola: bob" })).toHaveValue("admin");
    expect(screen.getByRole("button", { name: "Przekaż własność" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dziennik dostępu" })).toBeInTheDocument();
    const kinds = screen.getByRole("combobox", { name: "Rodzaj" });
    expect(
      within(kinds)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Dowolny", "Użytkownicy", "Grupy"]);

    await userEvent.click(rowPl("dave").getByRole("button", { name: "Usuń: dave" }));
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
