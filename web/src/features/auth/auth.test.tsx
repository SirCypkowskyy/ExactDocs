import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SetupPage, SignInPage, safeNext } from "./index";
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

const json = (body: unknown, status = 200) => Response.json(body, { status });
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
