import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { UsersPage } from "./index";
import { explainUserError, validateNewUser, validatePassword } from "./model/user";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const user = (id: string, username: string, extra = {}) => ({
  id,
  username,
  role: "user",
  created_at: "2026-11-13T10:00:00Z",
  disabled: false,
  last_active_at: null,
  token_count: 0,
  ...extra,
});
const json = (body: unknown, status = 200) => Response.json(body, { status });
const PASSWORD = "bob's long passphrase";

/** A tiny in-memory users API: list, create, disable, enable, reset. */
function stubApi() {
  let users = [
    user("a", "ada", { role: "admin", provider: null, groups: [] }),
    user("b", "bob", { provider: null, groups: [] }),
  ];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url.startsWith("/api/v1/users?") && method === "GET")
      return json({ users, next_cursor: null, total: users.length });
    if (url === "/api/v1/users" && method === "POST") {
      const body = JSON.parse(String(init?.body));
      if (users.some((u) => u.username === body.username.toLowerCase())) {
        return json({ error: "username_taken", detail: "taken", fields: [] }, 409);
      }
      const made = user(`id-${users.length}`, body.username, { role: body.role });
      users = [...users, made];
      return json(made, 201);
    }
    const toggled = url.match(/^\/api\/v1\/users\/([^/]+)\/(disable|enable)$/);
    if (toggled && method === "POST") {
      const [, id, action] = toggled;
      if (id === "a" && action === "disable") {
        return json({ error: "last_operator", detail: "last", fields: [] }, 409);
      }
      users = users.map((u) => (u.id === id ? { ...u, disabled: action === "disable" } : u));
      return json(users.find((u) => u.id === id));
    }
    const reset = url.match(/^\/api\/v1\/users\/([^/]+)\/password$/);
    if (reset && method === "PUT") {
      const account = users.find((u) => u.id === reset[1]);
      return json({ account, throttle: "cleared" });
    }
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage(currentUserId = "a") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TestRouter
          history={createMemoryHistory({ initialEntries: ["/users"] })}
          pages={{ "/users": () => <UsersPage currentUserId={currentUserId} /> }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

/** The table's row of an account (a card's list item on a phone). */
async function rowOf(name: string): Promise<HTMLElement> {
  const table = await screen.findByRole("table", { name: /User accounts|Konta użytkowników/ });
  const cell = await within(table).findByText(name);
  const row = cell.closest("tr");
  if (!row) throw new Error(`no row for ${name}`);
  return row;
}

/** Opens a row's "More actions" menu and returns it. */
async function menuOf(name: string, label = `More actions for ${name}`) {
  await userEvent.click(await screen.findByRole("button", { name: label }));
  return screen.findByRole("menu");
}

const items = (menu: HTMLElement) =>
  within(menu)
    .getAllByRole("menuitem")
    .map((item) => item.textContent);

const sent = (fetchMock: ReturnType<typeof stubApi>, method: string) =>
  fetchMock.mock.calls.filter(([, init]) => init?.method === method);

describe("users page", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists every account with its role and state, and marks the operator's own", async () => {
    stubApi();
    renderPage();
    const ada = await rowOf("ada");
    const bob = await rowOf("bob");
    expect(ada).toHaveTextContent(/ADada\s*You/);
    expect(ada).toHaveTextContent(/Admin.*Password.*Active/);
    expect(bob).toHaveTextContent(/User.*Password.*Active/);
    expect(screen.getByText("2 accounts")).toBeInTheDocument();
    // Nobody disables themselves from here (the server keeps the last admin anyway), nor resets
    // their own password (it would sign them out): the operator's own row only leads elsewhere.
    expect(items(await menuOf("ada"))).toEqual([
      "Show their API tokens",
      "Show their access-log entries",
    ]);
    await userEvent.keyboard("{Escape}");
    expect(items(await menuOf("bob"))).toEqual([
      "Show their API tokens",
      "Show their access-log entries",
      "Reset password…",
      "Disable…",
    ]);
  });

  it("offers the same actions in a context menu from the keyboard", async () => {
    stubApi();
    renderPage();
    const bob = await rowOf("bob");
    bob.focus();
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = await screen.findByRole("menu");
    expect(items(menu)).toEqual([
      "Show their API tokens",
      "Show their access-log entries",
      "Reset password…",
      "Disable…",
    ]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Disable…" }));
    expect(await screen.findByRole("alertdialog", { name: "Disable “bob”?" })).toBeInTheDocument();
  });

  it("creates a user after checking the form, and sends the chosen role", async () => {
    const fetchMock = stubApi();
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "New user" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Username"), "carol");
    await userEvent.type(within(dialog).getByLabelText("Password"), "short");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    expect(within(dialog).getByLabelText("Password")).toHaveFocus();
    expect(within(dialog).getByLabelText("Password")).toHaveAccessibleDescription(/12/);
    expect(sent(fetchMock, "POST")).toHaveLength(0);

    await userEvent.clear(within(dialog).getByLabelText("Password"));
    await userEvent.type(within(dialog).getByLabelText("Password"), PASSWORD);
    await userEvent.type(within(dialog).getByLabelText("Repeat password"), PASSWORD);
    await userEvent.selectOptions(within(dialog).getByLabelText("Role"), "admin");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(JSON.parse(String(sent(fetchMock, "POST")[0]?.[1]?.body))).toEqual({
      username: "carol",
      password: PASSWORD,
      role: "admin",
    });
    expect(await rowOf("carol")).toBeInTheDocument();
    expect(screen.getByText("User carol created.")).toHaveAttribute("role", "status");
    expect(toast.success).toHaveBeenCalledWith("User carol created", expect.anything());
    expect(document.body).not.toHaveTextContent(PASSWORD);
  });

  it("explains a taken username", async () => {
    stubApi();
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "New user" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Username"), "BOB");
    await userEvent.type(within(dialog).getByLabelText("Password"), PASSWORD);
    await userEvent.type(within(dialog).getByLabelText("Repeat password"), PASSWORD);
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    expect(await within(dialog).findByText(/already has that username/)).toBeInTheDocument();
  });

  it("disables only after confirmation, then offers to enable", async () => {
    const fetchMock = stubApi();
    renderPage();
    const kebab = await screen.findByRole("button", { name: "More actions for bob" });
    // With the mouse: the kebab never has focus while its menu is open.
    await userEvent.click(kebab);
    await userEvent.click(await screen.findByRole("menuitem", { name: "Disable…" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Disable “bob”?" });
    expect(confirm).toHaveTextContent(/signed out at once/);
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(sent(fetchMock, "POST")).toHaveLength(0);
    // Focus goes back to the row's menu button.
    await waitFor(() => expect(kebab).toHaveFocus());

    await userEvent.click(within(await menuOf("bob")).getByRole("menuitem", { name: "Disable…" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Disable" }),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(await within(await rowOf("bob")).findByText("Disabled")).toBeInTheDocument();
    expect(screen.getByText(/bob disabled\. Their sessions ended/)).toHaveAttribute(
      "role",
      "status",
    );
    expect(sent(fetchMock, "POST")[0]?.[0]).toBe("/api/v1/users/b/disable");

    await userEvent.click(within(await menuOf("bob")).getByRole("menuitem", { name: "Enable" }));
    await waitFor(() => expect(sent(fetchMock, "POST")[1]?.[0]).toBe("/api/v1/users/b/enable"));
    expect(await screen.findByText("bob enabled.")).toBeInTheDocument();
  });

  it("explains why the last admin stays enabled", async () => {
    stubApi();
    renderPage("b"); // signed in as another admin's view: ada can be targeted
    await userEvent.click(within(await menuOf("ada")).getByRole("menuitem", { name: "Disable…" }));
    const confirm = await screen.findByRole("alertdialog");
    await userEvent.click(within(confirm).getByRole("button", { name: "Disable" }));
    // The refusal shows inside the dialog, which stays open.
    expect(await within(confirm).findByText(/last enabled admin/)).toBeInTheDocument();
  });

  it("resets a password and says the user was signed out", async () => {
    const fetchMock = stubApi();
    renderPage();
    await userEvent.click(
      within(await menuOf("bob")).getByRole("menuitem", { name: "Reset password…" }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("New password"), PASSWORD);
    await userEvent.type(within(dialog).getByLabelText("Repeat password"), "something else!");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset password" }));
    expect(within(dialog).getByLabelText("Repeat password")).toHaveFocus();
    expect(sent(fetchMock, "PUT")).toHaveLength(0);

    await userEvent.clear(within(dialog).getByLabelText("Repeat password"));
    await userEvent.type(within(dialog).getByLabelText("Repeat password"), PASSWORD);
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset password" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(sent(fetchMock, "PUT")[0]?.[0]).toBe("/api/v1/users/b/password");
    expect(screen.getByText(/bob changed.*signed out/)).toHaveAttribute("role", "status");
  });

  it("offers no password reset of the operator's own disabled account, only Enable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({
          users: [user("a", "ada", { role: "admin", provider: null, disabled: true })],
          next_cursor: null,
          total: 1,
        }),
      ),
    );
    renderPage();
    expect(items(await menuOf("ada"))).toEqual([
      "Show their API tokens",
      "Show their access-log entries",
      "Enable",
    ]);
  });

  it("says plainly when the API refuses a non-operator", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ error: "forbidden", detail: "no", fields: [] }, 403)),
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(/only an admin/i);
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("user form rules", () => {
  it("mirrors the server's username and password rules", () => {
    const ok = { username: "bob", password: PASSWORD, confirm: PASSWORD };
    expect(validateNewUser(ok)).toEqual({});
    expect(validateNewUser({ ...ok, username: " " }).username).toMatch(/choose/i);
    expect(validateNewUser({ ...ok, username: "two words" }).username).toMatch(/spaces/);
    expect(validateNewUser({ ...ok, username: "x".repeat(65) }).username).toMatch(/64/);
    expect(validateNewUser({ ...ok, username: "a@Address:1" }).username).toMatch(/@address:/);
    expect(validatePassword("short", "short").password).toMatch(/12/);
    expect(validatePassword(PASSWORD, "other").confirm).toMatch(/match/);
  });

  it("turns every refusal into a sentence", () => {
    const refused = (status: number, error?: string) =>
      explainUserError(new HttpError(status, "/v1/users", error ? { error } : undefined));
    expect(refused(401)).toMatch(/session ended/);
    expect(refused(404, "unknown_account")).toMatch(/no longer exists/);
    expect(refused(500)).toMatch(/500/);
    expect(explainUserError(new TypeError("offline"))).toMatch(/can't reach/i);
  });

  it("names the field a validation error is about, not always the password", () => {
    const invalid = (loc: string[], msg: string) =>
      explainUserError(
        new HttpError(422, "/v1/users", {
          error: "validation_error",
          detail: "request is invalid",
          fields: [{ loc, msg, type: "string_too_long" }],
        }),
      );
    expect(invalid(["body", "username"], "String should have at most 256 characters")).toBe(
      "That username isn't accepted: String should have at most 256 characters.",
    );
    expect(invalid(["body", "password"], "Value error, too short")).toMatch(/^That password/);
    expect(invalid(["body", "role"], "Input should be 'admin' or 'user'")).toMatch(/refused role/);
    expect(
      explainUserError(
        new HttpError(422, "/v1/users", {
          error: "validation_error",
          detail: "request is invalid",
        }),
      ),
    ).toMatch(/request is invalid/);
  });

  it("shows where an account signs in, its groups, and offers no password reset for it", async () => {
    const accounts = [
      user("a", "ada", { role: "admin", provider: null, groups: [] }),
      user("c", "carol", { provider: "corp", groups: ["docs", "payments"] }),
      user("d", "dave", { provider: "corp", groups: [] }),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ users: accounts, next_cursor: null, total: 3 })),
    );
    renderPage();
    const ada = await rowOf("ada");
    const carol = await rowOf("carol");
    const dave = await rowOf("dave");
    expect(screen.getByRole("columnheader", { name: "Sign-in" })).toBeInTheDocument();
    expect(ada).toHaveTextContent(/Password/);
    expect(carol).toHaveTextContent(/corp/);
    expect(within(carol).getByText("docs")).toBeInTheDocument();
    expect(within(carol).getByText("payments")).toBeInTheDocument();
    expect(dave).toHaveTextContent(/corp–/);
    expect(items(await menuOf("carol"))).toEqual([
      "Show their API tokens",
      "Show their access-log entries",
      "Disable…",
    ]);
  });

  it("shows the first two groups and the rest on demand", async () => {
    const groups = ["docs", "payments", "search", "ops"];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({
          users: [user("c", "carol", { provider: "corp", groups })],
          next_cursor: null,
          total: 1,
        }),
      ),
    );
    renderPage();
    const carol = await rowOf("carol");
    expect(within(carol).queryByText("search")).not.toBeInTheDocument();
    await userEvent.click(within(carol).getByRole("button", { name: "2 more groups of carol" }));
    const all = await screen.findByRole("dialog");
    expect(within(all).getByText("Groups of carol")).toBeInTheDocument();
    expect(
      within(all)
        .getAllByRole("listitem")
        .map((g) => g.textContent),
    ).toEqual(groups);
  });

  it("explains that an account of an identity provider has no password", () => {
    const error = new HttpError(409, "/v1/users/c/password", {
      error: "external_account",
      detail: "no password",
      fields: [],
    });
    expect(explainUserError(error)).toMatch(/identity provider/);
  });
});

describe("users page in Polish", () => {
  beforeEach(() => setPreferences({ language: "pl" }));
  afterEach(() => {
    resetPreferences();
    vi.unstubAllGlobals();
  });

  it("names roles, states and actions in Polish", async () => {
    stubApi();
    renderPage();
    expect(await screen.findByRole("heading", { name: "Użytkownicy" })).toBeInTheDocument();
    expect(document.title).toBe("Użytkownicy - ExactDocs");
    const ada = await rowOf("ada");
    const bob = await rowOf("bob");
    expect(ada).toHaveTextContent(/ada\s*Ty/);
    expect(ada).toHaveTextContent(/Administrator.*Hasło.*Aktywne/);
    expect(bob).toHaveTextContent(/Użytkownik.*Hasło.*Aktywne/);
    expect(screen.getByText("2 konta")).toBeInTheDocument();
    expect(screen.getByText("1–2 z 2")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Logowanie" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rola" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Ostatnia aktywność/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Tokeny/ })).toBeInTheDocument();
    expect(within(bob).getByText("Nigdy")).toBeInTheDocument();
    const views = screen.getByRole("navigation", { name: "Widoki użytkowników" });
    expect(within(views).getByRole("link", { name: "Konta" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await userEvent.click(screen.getByRole("button", { name: "Logowanie" }));
    expect(await screen.findByRole("option", { name: "Hasło" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    const menu = await menuOf("bob", "Więcej opcji: bob");
    expect(items(menu)).toEqual([
      "Pokaż tokeny API tej osoby",
      "Pokaż wpisy tej osoby w dzienniku dostępu",
      "Zresetuj hasło…",
      "Wyłącz…",
    ]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Wyłącz…" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(within(confirm).getByText("Wyłączyć konto „bob”?")).toBeInTheDocument();
    expect(within(confirm).getByRole("button", { name: "Wyłącz" })).toBeInTheDocument();
  });

  it("checks a new account's password in Polish", async () => {
    stubApi();
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Nowy użytkownik" }));
    const dialog = await screen.findByRole("dialog", { name: "Nowy użytkownik" });
    await userEvent.type(within(dialog).getByLabelText("Nazwa użytkownika"), "carol");
    await userEvent.type(within(dialog).getByLabelText("Hasło"), "short");
    await userEvent.click(within(dialog).getByRole("button", { name: "Utwórz użytkownika" }));
    expect(within(dialog).getByLabelText("Hasło")).toHaveAccessibleDescription(
      "Co najmniej 12 znaków. Użyj co najmniej 12 znaków.",
    );
    expect(within(dialog).getByRole("option", { name: "Administrator" })).toBeInTheDocument();
  });

  it("explains refusals in Polish, keeping the server's reason", () => {
    expect(
      explainUserError(new HttpError(409, "/v1/users", { error: "username_taken" }), "pl"),
    ).toBe("Inne konto ma już tę nazwę użytkownika. Wybierz inną.");
    const invalid = new HttpError(422, "/v1/users", {
      error: "validation_error",
      detail: "request is invalid",
      fields: [{ loc: ["body", "password"], msg: "Value error, too short", type: "value_error" }],
    });
    expect(explainUserError(invalid, "pl")).toBe(
      "To hasło jest niedozwolone: Value error, too short.",
    );
    expect(validatePassword("pass", "other", "pl")).toEqual({
      password: "Użyj co najmniej 12 znaków.",
      confirm: "Hasła się różnią.",
    });
  });
});
