import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { UsersPage } from "./index";
import { explainUserError, validateNewUser, validatePassword } from "./model/user";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const user = (id: string, username: string, extra = {}) => ({
  id,
  username,
  role: "user",
  created_at: "2026-11-13T10:00:00Z",
  disabled: false,
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
      <UsersPage currentUserId={currentUserId} />
    </QueryClientProvider>,
  );
}

const sent = (fetchMock: ReturnType<typeof stubApi>, method: string) =>
  fetchMock.mock.calls.filter(([, init]) => init?.method === method);

describe("users page", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists every account with its role and state, and marks the operator's own", async () => {
    stubApi();
    renderPage();
    const list = await screen.findByRole("list", { name: "User accounts" });
    const [ada, bob] = within(list).getAllByRole("listitem") as [HTMLElement, HTMLElement];
    expect(ada).toHaveTextContent(/ada\s*You/);
    expect(ada).toHaveTextContent(/Admin\s*Active/);
    expect(bob).toHaveTextContent(/User\s*Active/);
    // Nobody disables themselves from here (the server keeps the last admin anyway).
    expect(within(ada).queryByRole("button", { name: /disable/i })).not.toBeInTheDocument();
    expect(within(bob).getByRole("button", { name: "Disable bob" })).toBeInTheDocument();
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
    expect(await screen.findByText("carol")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/carol created/);
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
    await userEvent.click(await screen.findByRole("button", { name: "Disable bob" }));
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm).toHaveTextContent(/signed out at once/);
    await userEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(sent(fetchMock, "POST")).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "Disable bob" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Disable" }),
    );
    expect(await screen.findByRole("button", { name: "Enable bob" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/bob disabled/);
    expect(sent(fetchMock, "POST")[0]?.[0]).toBe("/api/v1/users/b/disable");

    await userEvent.click(screen.getByRole("button", { name: "Enable bob" }));
    expect(await screen.findByRole("button", { name: "Disable bob" })).toBeInTheDocument();
  });

  it("explains why the last admin stays enabled", async () => {
    stubApi();
    renderPage("b"); // signed in as another admin's view: ada can be targeted
    await userEvent.click(await screen.findByRole("button", { name: "Disable ada" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Disable" }),
    );
    expect(await screen.findByText(/last enabled admin/)).toBeInTheDocument();
  });

  it("resets a password and says the user was signed out", async () => {
    const fetchMock = stubApi();
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Reset the password of bob" }));
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
    expect(screen.getByRole("status")).toHaveTextContent(/bob changed.*signed out/);
  });

  it("offers no password reset of the operator's own account, which would sign them out", async () => {
    stubApi();
    renderPage();
    const list = await screen.findByRole("list", { name: "User accounts" });
    const [ada, bob] = within(list).getAllByRole("listitem") as [HTMLElement, HTMLElement];
    expect(ada).toHaveTextContent(/You/);
    expect(
      within(ada).queryByRole("button", { name: /reset the password/i }),
    ).not.toBeInTheDocument();
    expect(
      within(bob).getByRole("button", { name: "Reset the password of bob" }),
    ).toBeInTheDocument();
  });

  it("says plainly when the API refuses a non-operator", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ error: "forbidden", detail: "no", fields: [] }, 403)),
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(/only an admin/i);
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
    const list = await screen.findByRole("list", { name: "User accounts" });
    const [ada, carol, dave] = within(list).getAllByRole("listitem") as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ];
    expect(ada).toHaveTextContent(/Password/);
    expect(carol).toHaveTextContent(/Signs in with corp/);
    expect(carol).toHaveTextContent(/Groups: docspayments/);
    expect(dave).toHaveTextContent(/No groups at the identity provider/);
    expect(
      within(carol).queryByRole("button", { name: /reset the password/i }),
    ).not.toBeInTheDocument();
    expect(within(carol).getByRole("button", { name: "Disable carol" })).toBeInTheDocument();
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
    const list = await screen.findByRole("list", { name: "Konta użytkowników" });
    const [ada, bob] = within(list).getAllByRole("listitem") as [HTMLElement, HTMLElement];
    expect(ada).toHaveTextContent(/ada\s*Ty/);
    expect(ada).toHaveTextContent(/Administrator\s*Aktywne/);
    expect(bob).toHaveTextContent(/Użytkownik\s*Aktywne/);
    expect(bob).toHaveTextContent("Utworzono 13 lis 2026");
    expect(screen.getByRole("button", { name: "Sortuj według: Konto" })).toBeInTheDocument();
    expect(screen.getByText("Wyświetlono 2 z 2")).toBeInTheDocument();

    await userEvent.click(within(bob).getByRole("button", { name: "Wyłącz konto bob" }));
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
