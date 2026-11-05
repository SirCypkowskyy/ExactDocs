import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { setUp, signIn } from "./api/session-query";
import { SetupPage, SignInPage, SignOutButton, safeNext } from "./index";
import { AdminCreated, explainError } from "./model/errors";
import { resolveGuard, validateSetup } from "./model/session";

describe("safeNext", () => {
  it.each(["/", "/libraries/x?y=1#z"])("keeps %s", (p) => expect(safeNext(p)).toBe(p));
  it.each([
    "https://evil.example/",
    "//evil.example",
    "/\\evil.example",
    "/%0d/ok\n",
    "libraries",
    "/sign-in?next=/",
    "/setup",
    undefined,
    42,
  ])("drops %s", (p) => expect(safeNext(p)).toBeUndefined());
});

describe("resolveGuard", () => {
  it("sends everything to setup on a fresh instance", () => {
    expect(resolveGuard("setup_required", "app", "/x")).toEqual({ to: "/setup" });
    expect(resolveGuard("setup_required", "sign-in", "/sign-in")).toEqual({ to: "/setup" });
    expect(resolveGuard("setup_required", "setup", "/setup")).toBeNull();
  });
  it("sends anonymous visitors to sign-in and remembers where they were going", () => {
    expect(resolveGuard("signed_out", "app", "/libraries/a?v=1")).toEqual({
      to: "/sign-in",
      search: { next: "/libraries/a?v=1" },
    });
    expect(resolveGuard("signed_out", "setup", "/setup")).toEqual({ to: "/sign-in", search: {} });
    expect(resolveGuard("signed_out", "sign-in", "/sign-in")).toBeNull();
  });
  it("keeps signed-in visitors out of the public pages", () => {
    expect(resolveGuard("signed_in", "app", "/")).toBeNull();
    expect(resolveGuard("signed_in", "sign-in", "/sign-in")).toEqual({ to: "/" });
    expect(resolveGuard("signed_in", "setup", "/setup")).toEqual({ to: "/" });
  });
});

describe("validateSetup", () => {
  it("asks for a long enough password, twice", () => {
    const ok = { username: "ada", password: "twelve chars!", confirm: "twelve chars!" };
    expect(validateSetup(ok)).toEqual({});
    expect(validateSetup({ ...ok, password: "short", confirm: "short" }).password).toMatch(/12/);
    expect(validateSetup({ ...ok, confirm: "other" }).confirm).toMatch(/match/);
    expect(validateSetup({ ...ok, username: "a b" }).username).toBeDefined();
  });
});

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const json = (body: unknown, status = 200, headers: HeadersInit = {}) =>
  Response.json(body, { status, headers });
const account = { id: "1", username: "ada", role: "admin" };

describe("sign-in form", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("explains missing fields without calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderWithClient(<SignInPage onSignedIn={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Enter your username.")).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toHaveFocus();
    expect(screen.getByLabelText("Username")).toHaveAccessibleDescription("Enter your username.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("announces a wrong password and keeps the visitor on the page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          { error: "invalid_credentials", detail: "invalid username or password", fields: [] },
          401,
        ),
      ),
    );
    const onSignedIn = vi.fn();
    renderWithClient(<SignInPage onSignedIn={onSignedIn} />);
    await userEvent.type(screen.getByLabelText("Username"), "ada");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("don't match");
    expect(screen.getByLabelText("Password")).toHaveFocus();
    expect(onSignedIn).not.toHaveBeenCalled();
  });

  it("asks the visitor to wait after too many failed sign-ins", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          {
            error: "rate_limited",
            detail: "too many failed sign-ins; try again in 5 seconds",
            fields: [],
          },
          429,
          { "Retry-After": "5" },
        ),
      ),
    );
    renderWithClient(<SignInPage onSignedIn={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Username"), "ada");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many failed sign-ins. Try again in 5 seconds.",
    );
  });

  it("signs in and returns to the requested page", async () => {
    const fetchMock = vi.fn(async () => json({ state: "signed_in", account }, 201));
    vi.stubGlobal("fetch", fetchMock);
    const onSignedIn = vi.fn();
    renderWithClient(<SignInPage next="/libraries/a" onSignedIn={onSignedIn} />);
    await userEvent.type(screen.getByLabelText("Username"), "ada");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith("/libraries/a"));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/session",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("says so when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    renderWithClient(<SignInPage onSignedIn={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Username"), "ada");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the server");
  });
});

describe("setup form", () => {
  afterEach(() => vi.unstubAllGlobals());

  async function fill(password = "twelve chars!", confirm = password) {
    await userEvent.type(screen.getByLabelText("Username"), "ada");
    await userEvent.type(screen.getByLabelText("Password"), password);
    await userEvent.type(screen.getByLabelText("Repeat the password"), confirm);
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
  }

  it("rejects a short password and a mismatch before calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderWithClient(<SetupPage onDone={vi.fn()} />);
    await fill("short");
    expect(screen.getByText("Use at least 12 characters.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("creates the admin, signs in, and finishes", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      url.endsWith("/setup") ? json(account, 201) : json({ state: "signed_in", account }, 201),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onDone = vi.fn();
    renderWithClient(<SetupPage onDone={onDone} />);
    await fill();
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/v1/setup", "/api/v1/session"]);
    // the backend rejects unknown fields: the repeat-password field must not be sent
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ username: "ada", password: "twelve chars!" });
  });

  it("points to sign-in when someone else finished setup first", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({ error: "already_set_up", detail: "already set up", fields: [] }, 409),
      ),
    );
    renderWithClient(<SetupPage onDone={vi.fn()} />);
    await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("already has an admin");
    expect(screen.getByRole("link", { name: "Sign in instead" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
  });
});

describe("form alert", () => {
  it("keeps an empty alert region and no visible message on first render", () => {
    renderWithClient(<SetupPage onDone={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/^$/);
  });
});

describe("explainError", () => {
  const http = (status: number, error: string, fields: unknown[] = []) =>
    new HttpError(status, "/v1/x", { error, detail: "d", fields: fields as never });

  it("maps 422 field problems onto the fields", () => {
    const problem = explainError(
      http(422, "validation_error", [
        { loc: ["body", "password"], msg: "too short", type: "string_too_short" },
        { loc: ["body", "username"], msg: "bad name", type: "x" },
      ]),
    );
    expect(problem.fields).toEqual({ password: "too short", username: "bad name" });
  });

  it("maps setup_required to a link to setup", () => {
    expect(explainError(http(403, "setup_required")).link?.href).toBe("/setup");
  });

  it("falls back to a server message for other statuses", () => {
    expect(explainError(http(500, "boom")).message).toMatch(/500/);
  });
});

describe("session calls", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("clears the previous account's data when someone signs in", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ state: "signed_in", account }, 201)),
    );
    const client = new QueryClient();
    client.setQueryData(["libraries", "list"], ["private"]);
    await signIn(client, { username: "ada", password: "x" });
    expect(client.getQueryData(["libraries", "list"])).toBeUndefined();
    expect(client.getQueryData(["session"])).toMatchObject({ state: "signed_in" });
  });

  it("tells the visitor the admin exists when only the sign-in after setup fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/setup") ? json(account, 201) : json({ error: "x", detail: "x" }, 500),
      ),
    );
    await expect(
      setUp(new QueryClient(), { username: "ada", password: "x" }),
    ).rejects.toBeInstanceOf(AdminCreated);
    expect(explainError(new AdminCreated())).toMatchObject({
      message: expect.stringContaining("created"),
      link: { href: "/sign-in" },
    });
  });

  it("signs out: sends DELETE, drops cached data, marks the session signed out", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient();
    client.setQueryData(["libraries", "list"], ["private"]);
    client.setQueryData(["session"], { state: "signed_in", account });
    const onSignedOut = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <SignOutButton onSignedOut={onSignedOut} />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(onSignedOut).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/session",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(client.getQueryData(["libraries", "list"])).toBeUndefined();
    expect(client.getQueryData(["session"])).toEqual({ state: "signed_out" });
  });

  it("keeps the visitor signed in and says so when sign-out fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const client = new QueryClient();
    client.setQueryData(["session"], { state: "signed_in", account });
    const onSignedOut = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <SignOutButton onSignedOut={onSignedOut} />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't sign out");
    expect(onSignedOut).not.toHaveBeenCalled();
    expect(client.getQueryData(["session"])).toMatchObject({ state: "signed_in" });
  });
});
