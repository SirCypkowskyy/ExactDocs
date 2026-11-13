import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { UsersPage } from "./index";
import { explainUserError, validateNewUser, validatePassword } from "./model/user";

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
  let users = [user("a", "ada", { role: "admin" }), user("b", "bob")];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/v1/users" && method === "GET") return json({ users });
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
    const [ada, bob] = within(list).getAllByRole("listitem");
    expect(ada).toHaveTextContent(/ada\s*\(you\)/);
    expect(ada).toHaveTextContent(/Admin · Active/);
    expect(bob).toHaveTextContent(/User · Active/);
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
    expect(refused(422)).toMatch(/password/);
    expect(refused(500)).toMatch(/500/);
    expect(explainUserError(new TypeError("offline"))).toMatch(/can't reach/i);
  });
});
