import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { TokensSection } from "./index";
import { expiresAt, explainTokenError, MAX_TOKENS } from "./model/token";

const SECRET = "exd_SECRET_VALUE_0123456789";
const row = (n: number, extra = {}) => ({
  id: `id-${n}`,
  name: `token ${n}`,
  prefix: `exd_ab${n}`,
  created_at: "2026-11-01T10:00:00Z",
  expires_at: null,
  last_used_at: null,
  library_ids: null,
  ...extra,
});
const json = (body: unknown, status = 200) => Response.json(body, { status });

/** A tiny in-memory API: list, create (returns the secret once), revoke. */
function stubApi(initial: ReturnType<typeof row>[] = []) {
  let tokens = [...initial];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url.startsWith("/api/v1/tokens?") && method === "GET")
      return json({ tokens, next_cursor: null, total: tokens.length });
    if (url === "/api/v1/tokens" && method === "POST") {
      const body = JSON.parse(String(init?.body));
      const made = row(tokens.length + 1, { name: body.name, expires_at: body.expires_at ?? null });
      tokens = [made, ...tokens];
      return json({ ...made, token: SECRET }, 201);
    }
    if (url.startsWith("/api/v1/tokens/") && method === "DELETE") {
      tokens = tokens.filter((t) => t.id !== url.split("/").pop());
      return new Response(null, { status: 204 });
    }
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TestRouter
          history={createMemoryHistory({ initialEntries: ["/account"] })}
          pages={{ "/account": TokensSection }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return client;
}

/** A token's row in the table. */
async function rowOf(name: string): Promise<HTMLElement> {
  const table = await screen.findByRole("table", { name: /API tokens|Tokeny API/ });
  const cell = await within(table).findByRole("rowheader", { name: new RegExp(`^${name}$`) });
  return cell.closest("tr") as HTMLElement;
}

/** Opens a token's "More actions" menu with the mouse; focus comes back to the kebab after. */
async function openMenu(name: string, label = `More actions for ${name}`) {
  const kebab = await screen.findByRole("button", { name: label });
  await userEvent.click(kebab);
  return { kebab, menu: await screen.findByRole("menu") };
}

describe("tokens", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  const clipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
  afterEach(() => {
    vi.unstubAllGlobals();
    if (clipboard) Object.defineProperty(navigator, "clipboard", clipboard);
    else Reflect.deleteProperty(navigator, "clipboard");
  });

  it("teaches what tokens are when there are none", async () => {
    stubApi();
    renderSection();
    expect(await screen.findByText(/no tokens yet/i)).toBeInTheDocument();
  });

  it("shows a ready-to-paste MCP config with this server's origin and a placeholder token", async () => {
    stubApi();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderSection();
    const config = await screen.findByRole("region", { name: "MCP client config" });
    expect(config).toHaveTextContent(`${window.location.origin}/mcp`);
    expect(config).toHaveTextContent("Bearer exd_YOUR_TOKEN");
    await userEvent.click(screen.getByRole("button", { name: "Copy config" }));
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining(`${window.location.origin}/mcp`),
    );
    expect(await screen.findByRole("button", { name: "Config copied" })).toBeInTheDocument();
  });

  it("lists name, expiry and last use, never a secret", async () => {
    stubApi([
      row(1, { expires_at: "2099-01-01T00:00:00Z" }),
      row(2, { expires_at: "2020-01-01T00:00:00Z" }),
    ]);
    renderSection();
    await rowOf("token 1");
    const table = screen.getByRole("table", { name: "API tokens" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    for (const row of rows) expect(row).toHaveTextContent(/never used/i);
    expect(within(table).getByText(/^Expired/)).toBeInTheDocument();
    expect(table).not.toHaveTextContent(SECRET);
  });

  it("creates a selected-library token and displays its scope", async () => {
    const request = stubApi([row(1, { library_ids: [] }), row(2, { library_ids: ["/acme/api"] })]);
    renderSection();
    expect(await screen.findByText("No libraries")).toBeInTheDocument();
    expect(screen.getByText("/acme/api")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New token" }));
    await userEvent.type(screen.getByLabelText("Name"), "limited");
    await userEvent.selectOptions(screen.getByLabelText("Library access"), "selected");
    await userEvent.type(screen.getByLabelText("Library IDs"), "/acme/docs, /acme/api");
    await userEvent.click(screen.getByRole("button", { name: "Create token" }));
    await screen.findByText(SECRET);
    const post = request.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body)).library_ids).toEqual(["/acme/docs", "/acme/api"]);
  });

  it("shows the secret once, copies it, and drops it from every store", async () => {
    stubApi();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const client = renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "New token" }));
    await userEvent.type(screen.getByLabelText("Name"), "laptop");
    await userEvent.selectOptions(
      within(screen.getByRole("dialog")).getByLabelText("Expires"),
      "30",
    );
    await userEvent.click(screen.getByRole("button", { name: "Create token" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(SECRET)).toBeInTheDocument();
    expect(within(dialog).getByText(/only time/i)).toBeInTheDocument();
    const copy = within(dialog).getByRole("button", { name: /copy token/i });
    expect(copy).toHaveFocus();
    await userEvent.click(copy);
    expect(writeText).toHaveBeenCalledWith(SECRET);
    expect(await within(dialog).findByRole("button", { name: /copied/i })).toBeInTheDocument();

    // not in the query cache, the mutation cache, or browser storage while it is on screen
    const cached = JSON.stringify([
      client
        .getQueryCache()
        .getAll()
        .map((q) => q.state.data),
      client
        .getMutationCache()
        .getAll()
        .map((m) => m.state.data),
      { ...localStorage },
      { ...sessionStorage },
    ]);
    expect(cached).not.toContain(SECRET);

    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.body).not.toHaveTextContent(SECRET);
    expect(
      JSON.stringify(
        client
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data),
      ),
    ).not.toContain(SECRET);
    expect(await rowOf("laptop")).toBeInTheDocument();
    expect(screen.getByText("Token laptop created.")).toHaveAttribute("role", "status");
  });

  it("sends the expiry as a future timestamp, and none when there is no expiry", () => {
    const now = Date.UTC(2026, 10, 4);
    expect(expiresAt("never", now)).toBeUndefined();
    expect(expiresAt("30", now)).toBe("2026-12-04T00:00:00.000Z");
  });

  it("asks for a name before calling the API", async () => {
    const fetchMock = stubApi();
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "New token" }));
    await userEvent.click(screen.getByRole("button", { name: "Create token" }));
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(/name/i);
    expect(fetchMock.mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(0);
  });

  it("explains a refused create (409 too_many_tokens)", async () => {
    const fetchMock = stubApi();
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "New token" }));
    await userEvent.type(screen.getByLabelText("Name"), "x");
    fetchMock.mockImplementationOnce(async () =>
      json({ error: "too_many_tokens", detail: "limit", fields: [] }, 409),
    );
    await userEvent.click(screen.getByRole("button", { name: "Create token" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/50 tokens/));
  });

  it("revokes only after confirmation, then moves focus somewhere real", async () => {
    stubApi([row(1), row(2)]);
    renderSection();
    const first = await openMenu("token 1");
    expect(
      within(first.menu)
        .getAllByRole("menuitem")
        .map((item) => item.textContent),
    ).toEqual(["Copy prefix", "Revoke…"]);
    await userEvent.click(within(first.menu).getByRole("menuitem", { name: "Revoke…" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Revoke “token 1”?" });
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(await rowOf("token 1")).toBeInTheDocument();
    // Kept: focus goes back to the row's menu button.
    await waitFor(() => expect(first.kebab).toHaveFocus());

    const again = await openMenu("token 1");
    await userEvent.click(within(again.menu).getByRole("menuitem", { name: "Revoke…" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
    );
    await waitFor(() => expect(screen.queryByText("token 1")).not.toBeInTheDocument());
    expect(screen.getByText("token 1 revoked.")).toHaveAttribute("role", "status");
    // Gone: focus lands on the section.
    expect(screen.getByRole("heading", { name: "API tokens" })).toHaveFocus();
  });

  it("offers the same actions in a context menu, and copies the prefix", async () => {
    stubApi([row(1)]);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderSection();
    const token = await rowOf("token 1");
    token.focus();
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = await screen.findByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((item) => item.textContent),
    ).toEqual(["Copy prefix", "Revoke…"]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Copy prefix" }));
    expect(writeText).toHaveBeenCalledWith("exd_ab1");
  });

  it("stops at the limit", async () => {
    const fetchMock = stubApi(Array.from({ length: MAX_TOKENS }, (_, i) => row(i + 1)));
    renderSection();
    expect(await screen.findByText(/revoke one/i)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "New token" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(button);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows a loading state, then an error with a retry", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("offline"));
    vi.stubGlobal("fetch", fetchMock);
    renderSection();
    expect(await screen.findByRole("table", { name: "API tokens" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/can't reach the server/i);
    stubApi([row(1)]);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await rowOf("token 1")).toBeInTheDocument();
  });

  async function openAndCreate(name = "laptop") {
    await userEvent.click(await screen.findByRole("button", { name: "New token" }));
    await userEvent.type(screen.getByLabelText("Name"), name);
    await userEvent.click(screen.getByRole("button", { name: "Create token" }));
  }

  it("cannot be closed by Escape or an outside click while the secret is shown", async () => {
    stubApi();
    renderSection();
    await openAndCreate();
    const dialog = await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    fireEvent.pointerDown(document.body);
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(within(dialog).getByText(SECRET)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // the guard is reset: the next form closes normally
    await userEvent.click(screen.getByRole("button", { name: "New token" }));
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the dialog open while the create request is in flight", async () => {
    const fetchMock = stubApi();
    let release: (r: Response) => void = () => {};
    renderSection();
    await screen.findByText(/no tokens yet/i);
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    await openAndCreate();
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    release(json({ ...row(1, { name: "laptop" }), token: SECRET }, 201));
    expect(await screen.findByText(SECRET)).toBeInTheDocument();
  });

  it("closes the form with Cancel and creates nothing", async () => {
    const fetchMock = stubApi();
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "New token" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(0);
  });

  it.each([
    ["rejects", { writeText: vi.fn().mockRejectedValue(new Error("denied")) }],
    ["is missing", undefined],
  ])("selects the secret for Ctrl+C when the clipboard %s", async (_, value) => {
    stubApi();
    Object.defineProperty(navigator, "clipboard", { value, configurable: true });
    renderSection();
    await openAndCreate();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /copy token/i }));
    expect(await within(dialog).findByText(/press Ctrl\+C/)).toBeInTheDocument();
    expect(window.getSelection()?.toString()).toBe(SECRET);
  });

  it("treats revoking an already-revoked token as done", async () => {
    const fetchMock = stubApi([row(1)]);
    renderSection();
    await userEvent.click(
      within((await openMenu("token 1")).menu).getByRole("menuitem", { name: "Revoke…" }),
    );
    fetchMock.mockImplementationOnce(async () =>
      json({ error: "unknown_token", detail: "gone", fields: [] }, 404),
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByText("token 1 revoked.")).toHaveAttribute("role", "status");
  });

  it("offers sign-in when the session ended during create, and refetches the list", async () => {
    const fetchMock = stubApi();
    renderSection();
    await screen.findByText(/no tokens yet/i);
    fetchMock.mockImplementationOnce(async () =>
      json({ error: "unauthenticated", detail: "no", fields: [] }, 401),
    );
    await openAndCreate();
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([u, i]) => String(u).startsWith("/api/v1/tokens?") && !i?.method,
        ).length,
      ).toBeGreaterThan(1),
    );
  });
});

describe("tokens in Polish", () => {
  beforeEach(() => {
    localStorage.clear();
    setPreferences({ language: "pl" });
  });
  afterEach(() => {
    resetPreferences();
    vi.unstubAllGlobals();
  });

  it("lists tokens with Polish words, dates and counts", async () => {
    stubApi([
      row(1, { expires_at: "2099-01-01T00:00:00Z", library_ids: [] }),
      row(2, { last_used_at: "2026-11-02T10:00:00Z" }),
    ]);
    renderSection();
    expect(await screen.findByRole("heading", { name: "Tokeny API" })).toBeInTheDocument();
    const first = await rowOf("token 1");
    const second = await rowOf("token 2");
    expect(first).toHaveTextContent("Nigdy nieużywany");
    expect(first).toHaveTextContent("Brak bibliotek");
    expect(second).toHaveTextContent("Bezterminowy");
    expect(second).toHaveTextContent("Wszystkie biblioteki, do których masz dostęp");
    expect(
      within(first).getByRole("button", { name: "Kopiuj: prefiks tokenu" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Ostatnio użyty/ })).toBeInTheDocument();
    expect(screen.getByText("1–2 z 2")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Konfiguracja klienta MCP" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Wygasa" }));
    expect(
      await screen.findByRole("option", { name: /Wygasają w ciągu 7 dni/ }),
    ).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    const { menu } = await openMenu("token 1", "Więcej opcji: token 1");
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Unieważnij…" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(within(confirm).getByText("Unieważnić token „token 1”?")).toBeInTheDocument();
    expect(confirm).toHaveTextContent("od razu przestanie działać. Tego nie można cofnąć.");
    expect(within(confirm).getByRole("button", { name: "Anuluj" })).toBeInTheDocument();
  });

  it("asks for a name in Polish and offers Polish expiry choices", async () => {
    stubApi();
    renderSection();
    expect(await screen.findByText("Nie ma jeszcze tokenów")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Nowy token" }));
    const dialog = await screen.findByRole("dialog", { name: "Nowy token API" });
    expect(within(dialog).getByRole("option", { name: "Za 30 dni" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Utwórz token" }));
    expect(
      within(dialog).getByText("Nazwij token od miejsca, w którym będzie używany, np. „laptop”."),
    ).toBeInTheDocument();
  });

  it("explains the token limit with a Polish plural", () => {
    const full = new HttpError(409, "/v1/tokens", { error: "too_many_tokens" });
    expect(explainTokenError(full, "pl")).toMatch(/^Masz 50 tokenów, czyli najwięcej/);
    expect(explainTokenError(full, "en")).toMatch(/^You have 50 tokens, the most/);
  });
});
