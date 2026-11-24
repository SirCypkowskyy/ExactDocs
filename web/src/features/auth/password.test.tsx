import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { SignInSettings } from "./index";
import { describeWait, explainPasswordError, validatePasswordChange } from "./model/password";

const account = { id: "1", username: "ada", role: "user", has_password: true };
const signedIn = { state: "signed_in", account, source: "session", providers: [] };

const json = (body: unknown, status = 200, headers: HeadersInit = {}) =>
  Response.json(body, { status, headers });
const refusal = (
  status: number,
  error: string,
  headers: HeadersInit = {},
  fields: unknown[] = [],
) => json({ error, detail: error, fields }, status, headers);

function mount(session: unknown = signedIn, respond?: () => Response | Promise<Response>) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
    respond ? respond() : new Response(null, { status: 204 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["session"], session);
  render(
    <QueryClientProvider client={client}>
      <SignInSettings />
    </QueryClientProvider>,
  );
  return { client, fetchMock };
}

const current = () => screen.getByLabelText("Current password");
const next = () => screen.getByLabelText("New password");
const confirm = () => screen.getByLabelText("Repeat the new password");
const submit = () => screen.getByRole("button", { name: "Change password" });

async function fill(values: { current?: string; next?: string; confirm?: string } = {}) {
  const v = { current: "old password!", next: "a brand new phrase", ...values };
  if (v.current) await userEvent.type(current(), v.current);
  if (v.next) await userEvent.type(next(), v.next);
  const repeat = values.confirm ?? v.next;
  if (repeat) await userEvent.type(confirm(), repeat);
}

describe("Account → Sign-in → Password", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    resetPreferences();
  });

  it("offers three password boxes a password manager understands, with a length hint", () => {
    mount();
    expect(screen.getByRole("heading", { name: "Password" })).toBeInTheDocument();
    expect(current()).toHaveAttribute("type", "password");
    expect(current()).toHaveAttribute("autocomplete", "current-password");
    expect(next()).toHaveAttribute("autocomplete", "new-password");
    expect(confirm()).toHaveAttribute("autocomplete", "new-password");
    expect(next()).toHaveAccessibleDescription(/^12 to 1024 characters\./);
    expect(submit()).toBeInTheDocument();
  });

  it("checks the boxes before calling the server and sends focus to the first wrong one", async () => {
    const { fetchMock } = mount();
    await userEvent.click(submit());
    expect(current()).toHaveFocus();
    expect(current()).toHaveAccessibleDescription("Enter your current password.");
    expect(next()).toHaveAccessibleDescription(/Use at least 12 characters\./);

    await userEvent.type(current(), "old password!");
    await userEvent.type(next(), "short");
    await userEvent.click(submit());
    expect(next()).toHaveFocus();
    expect(next()).toHaveAttribute("aria-invalid", "true");

    await userEvent.clear(next());
    await userEvent.type(next(), "a brand new phrase");
    await userEvent.type(confirm(), "a brand new phrasf");
    await userEvent.click(submit());
    expect(confirm()).toHaveFocus();
    expect(confirm()).toHaveAccessibleDescription("The passwords don't match.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a new password over 1024 characters before sending it", async () => {
    const { fetchMock } = mount();
    await userEvent.type(current(), "old password!");
    // userEvent.type is slow for 1025 keys: paste the long one.
    await userEvent.click(next());
    await userEvent.paste("x".repeat(1025));
    await userEvent.click(confirm());
    await userEvent.paste("x".repeat(1025));
    await userEvent.click(submit());
    expect(next()).toHaveFocus();
    expect(next()).toHaveAccessibleDescription(/Use at most 1024 characters\./);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("changes the password (204), clears the boxes and says the other sessions ended", async () => {
    const success = vi.spyOn(toast, "success");
    const { client, fetchMock } = mount();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Show new password" }));
    expect(next()).toHaveAttribute("type", "text");
    await userEvent.click(submit());

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Password changed. Your other sessions were signed out.",
    );
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/account/password");
    expect(init.method).toBe("PUT");
    // Only the two fields the API takes: the repeat box stays in the browser.
    expect(JSON.parse(String(init.body))).toEqual({
      current_password: "old password!",
      new_password: "a brand new phrase",
    });
    for (const box of [current(), next(), confirm()]) {
      expect(box).toHaveValue("");
      expect(box).toHaveAttribute("type", "password");
    }
    expect(success).toHaveBeenCalledWith(
      "Password changed",
      expect.objectContaining({
        description: "Your other sessions were signed out. Your API tokens keep working.",
      }),
    );
    // This session stays: nothing about it changed in the cache.
    expect(client.getQueryData(["session"])).toEqual(signedIn);
  });

  it("keeps the person signed in on a wrong current password (403) and says so at that box", async () => {
    const { client } = mount(signedIn, () => refusal(403, "wrong_password"));
    await fill();
    await userEvent.click(submit());
    await waitFor(() => expect(current()).toHaveFocus());
    expect(current()).toHaveAttribute("aria-invalid", "true");
    expect(current()).toHaveAccessibleDescription("That isn't your current password.");
    expect(screen.getByRole("alert")).toHaveTextContent(/^$/);
    // The typed new password stays, so only the current one needs typing again.
    expect(next()).toHaveValue("a brand new phrase");
    expect(client.getQueryData(["session"])).toEqual(signedIn);
  });

  it("says when to try again after too many wrong passwords (429, Retry-After)", async () => {
    mount(signedIn, () => refusal(429, "rate_limited", { "Retry-After": "90" }));
    await fill();
    await userEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many wrong passwords. Try again in 2 minutes.",
    );
  });

  it("asks for a little patience when the server gives no Retry-After", async () => {
    mount(signedIn, () => refusal(429, "rate_limited"));
    await fill();
    await userEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many wrong passwords. Wait a little, then try again.",
    );
  });

  it("puts the server's length refusal (422) on the new password box", async () => {
    mount(signedIn, () =>
      refusal(422, "validation_error", {}, [
        {
          loc: ["body", "new_password"],
          msg: "String should have at least 12 characters",
          type: "x",
        },
      ]),
    );
    await fill();
    await userEvent.click(submit());
    await waitFor(() => expect(next()).toHaveFocus());
    expect(next()).toHaveAccessibleDescription(
      /The server refused this password\. Use 12 to 1024 characters\./,
    );
  });

  it("gives way to the sign-in note when the server says there is no password (409)", async () => {
    const providers = [{ name: "google", display_name: "Google" }];
    const { client } = mount({ ...signedIn, providers }, () => refusal(409, "external_account"));
    await fill();
    await userEvent.click(submit());
    const note = await screen.findByText(
      "You sign in with Google, so there is no ExactDocs password to change here.",
    );
    expect(note.closest("p")).toHaveFocus();
    expect(screen.queryByLabelText("Current password")).toBeNull();
    expect(client.getQueryData(["session"])).toMatchObject({ account: { has_password: false } });
  });

  it("says the session ended on a 401 and links to sign-in", async () => {
    mount(signedIn, () => refusal(401, "unauthenticated"));
    await fill();
    await userEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent("Your session has ended.");
    expect(screen.getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/sign-in");
  });

  it("says so when the server cannot be reached", async () => {
    mount(signedIn, () => Promise.reject(new TypeError("offline")));
    await fill();
    await userEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the server");
  });

  it("shows the busy state and sends one request however often it is pressed", async () => {
    let finish: (r: Response) => void = () => {};
    const { fetchMock } = mount(
      signedIn,
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    );
    await fill();
    await userEvent.click(submit());
    const busy = await screen.findByRole("button", { name: "Changing password" });
    expect(busy).toHaveAttribute("aria-busy", "true");
    await userEvent.click(busy);
    await userEvent.keyboard("{Enter}");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    finish(new Response(null, { status: 204 }));
    expect(await screen.findByRole("button", { name: "Change password" })).toBeInTheDocument();
  });

  it("works from the keyboard: each box, then its toggle, then the button; Enter sends", async () => {
    const { fetchMock } = mount();
    await userEvent.tab();
    expect(current()).toHaveFocus();
    await userEvent.keyboard("old password!");
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Show current password" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(current()).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Hide current password" })).toHaveFocus();
    await userEvent.tab();
    expect(next()).toHaveFocus();
    await userEvent.keyboard("a brand new phrase");
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Show new password" })).toHaveFocus();
    await userEvent.tab();
    expect(confirm()).toHaveFocus();
    await userEvent.keyboard("a brand new phrase");
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Show repeated password" })).toHaveFocus();
    await userEvent.tab();
    expect(submit()).toHaveFocus();
    await userEvent.click(confirm());
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });

  it("offers no form to an account without a password, and names how it signs in", () => {
    mount({ ...signedIn, account: { ...account, has_password: false }, providers: [] });
    expect(screen.getByRole("heading", { name: "Password" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "You sign in through an identity provider, so there is no ExactDocs password to change here.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change password" })).toBeNull();
    expect(screen.queryByLabelText("Current password")).toBeNull();
  });

  it("names Cloudflare Access for an account signed in through it", () => {
    mount({
      ...signedIn,
      account: { ...account, has_password: false },
      source: "cloudflare_access",
    });
    expect(
      screen.getByText(
        "You sign in through Cloudflare Access, so there is no ExactDocs password to change here.",
      ),
    ).toBeInTheDocument();
  });

  it("speaks Polish", async () => {
    setPreferences({ language: "pl" });
    mount(signedIn, () => refusal(429, "rate_limited", { "Retry-After": "300" }));
    expect(screen.getByRole("heading", { name: "Hasło" })).toBeInTheDocument();
    expect(screen.getByLabelText("Nowe hasło")).toHaveAccessibleDescription(
      /^Od 12 do 1024 znaków\./,
    );
    await userEvent.type(screen.getByLabelText("Obecne hasło"), "old password!");
    await userEvent.type(screen.getByLabelText("Nowe hasło"), "a brand new phrase");
    await userEvent.type(screen.getByLabelText("Powtórz nowe hasło"), "a brand new phrase");
    expect(screen.getByRole("button", { name: "Pokaż obecne hasło" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Zmień hasło" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Zbyt wiele błędnych haseł. Spróbuj ponownie za 5 minut.",
    );
  });
});

describe("password model", () => {
  it("puts a wait in words a person can act on", () => {
    expect(describeWait(1, "en")).toBe("Try again in 1 second.");
    expect(describeWait(45, "en")).toBe("Try again in 45 seconds.");
    expect(describeWait(61, "en")).toBe("Try again in 2 minutes.");
    expect(describeWait(3600, "en")).toBe("Try again in 1 hour.");
    expect(describeWait(2, "pl")).toBe("Spróbuj ponownie za 2 sekundy.");
    expect(describeWait(60, "pl")).toBe("Spróbuj ponownie za 1 minutę.");
    expect(describeWait(7200, "pl")).toBe("Spróbuj ponownie za 2 godziny.");
  });

  it("follows the setup's limits", () => {
    const ok = { current: "x", next: "twelve chars!", confirm: "twelve chars!" };
    expect(validatePasswordChange(ok, "en")).toEqual({});
    expect(
      validatePasswordChange({ ...ok, next: "x".repeat(1024), confirm: "x".repeat(1024) }, "en"),
    ).toEqual({});
    expect(validatePasswordChange({ ...ok, current: "" }, "en").current).toBeDefined();
  });

  it("falls back to the server's status for anything else", () => {
    const error = new HttpError(500, "/v1/account/password", { error: "boom", detail: "d" });
    expect(explainPasswordError(error, "en").message).toMatch(/500/);
  });
});
