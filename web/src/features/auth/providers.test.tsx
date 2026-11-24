import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { browser } from "./api/providers-query";
import { SignInPage, SignInSettings } from "./index";
import { explainLinkError } from "./model/providers";

/* Account → Sign-in → Linked sign-in providers (#506). */

const account = { id: "1", username: "ada", role: "member", has_password: false };
const configured = [
  { name: "google", display_name: "Google", icon: "google" },
  { name: "gh", display_name: "GitHub", icon: "github" },
  { name: "corp", display_name: "Corp SSO", icon_url: "/api/v1/auth/corp/icon?v=1" },
] as const;
const signedIn = { state: "signed_in", account, source: "session", providers: configured };

type Row = Record<string, unknown> & { name: string };
const row = (over: Row) => ({
  display_name: over.name,
  icon: null,
  icon_url: null,
  configured: true,
  linked: false,
  origin: false,
  linked_at: null,
  last_signed_in_at: null,
  can_link: true,
  can_unlink: false,
  ...over,
});
const google = row({
  name: "google",
  display_name: "Google",
  icon: "google",
  linked: true,
  origin: true,
  last_signed_in_at: "2026-11-20T09:00:00Z",
  can_link: false,
});
const github = row({
  name: "gh",
  display_name: "GitHub",
  icon: "github",
  linked: true,
  linked_at: "2026-11-03T10:00:00Z",
  last_signed_in_at: "2026-11-03T10:00:00Z",
  can_link: false,
  can_unlink: true,
});
const corp = row({
  name: "corp",
  display_name: "Corp SSO",
  icon_url: "/api/v1/auth/corp/icon?v=1",
});
const old = row({
  name: "old",
  display_name: "Old SSO",
  configured: false,
  linked: true,
  linked_at: "2026-01-10T10:00:00Z",
  can_link: false,
  can_unlink: true,
});
const LIST = { has_password: false, providers: [google, github, corp, old] };

const json = (body: unknown, status = 200) => Response.json(body, { status });
const refusal = (status: number, error: string) =>
  json({ error, detail: error, fields: [] }, status);

type Handler = (init: RequestInit | undefined) => Response | Promise<Response>;

function mount({
  session = signedIn as unknown,
  routes = {} as Record<string, Handler>,
  props = {} as Parameters<typeof SignInSettings>[0],
} = {}) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const handler = routes[key];
    if (handler) return handler(init);
    if (key === "GET /api/v1/account/providers") return json(LIST);
    return refusal(500, "unexpected");
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["session"], session);
  const view = render(
    <QueryClientProvider client={client}>
      <SignInSettings {...props} />
    </QueryClientProvider>,
  );
  const calls = (key: string) =>
    fetchMock.mock.calls.filter(([url, init]) => `${init?.method ?? "GET"} ${url}` === key);
  return { client, fetchMock, calls, view };
}

const list = () => screen.findByRole("list", { name: "Sign-in providers" });
const item = async (name: string) => {
  const items = within(await list()).getAllByRole("listitem");
  const found = items.find((li) => li.querySelector("p")?.textContent?.startsWith(name));
  if (!found) throw new Error(`no row for ${name}`);
  return found;
};

describe("Account → Sign-in → Linked sign-in providers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    resetPreferences();
  });

  it("lists every provider with its mark, whether it is linked and since when, and its action", async () => {
    mount();
    expect(screen.getByRole("heading", { name: "Linked sign-in providers" })).toBeInTheDocument();
    // While the list loads: a skeleton, said once to screen readers.
    expect(screen.getByRole("status")).toHaveTextContent("Loading sign-in providers");

    const origin = await item("Google");
    expect(origin).toHaveTextContent("Created your account");
    expect(within(origin).getByText("Linked")).toBeInTheDocument();
    expect(origin.querySelector('svg[data-brand="google"]')).toBeInTheDocument();

    const gh = await item("GitHub");
    expect(within(gh).getByText(/^Linked · since Nov 3, 2026$/)).toHaveAttribute(
      "datetime",
      "2026-11-03T10:00:00Z",
    );
    expect(within(gh).getByRole("button", { name: "Unlink GitHub" })).toBeEnabled();

    const own = await item("Corp SSO");
    expect(own).toHaveTextContent("Not linked");
    const linkButton = within(own).getByRole("button", { name: "Link Corp SSO" });
    expect(linkButton.querySelector("img")).toHaveAttribute("src", "/api/v1/auth/corp/icon?v=1");

    const gone = await item("Old SSO");
    expect(gone).toHaveTextContent("No longer offered by this server");
    expect(within(gone).getByRole("button", { name: "Unlink Old SSO" })).toBeInTheDocument();
  });

  it("keeps the only way in: the origin of an account without a password cannot be unlinked", async () => {
    const { calls } = mount();
    const button = within(await item("Google")).getByRole("button", { name: "Unlink Google" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(
      "This is your only way to sign in: the account was created with Google and has no password, so it can't be unlinked.",
    );
    await userEvent.click(button);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(calls("DELETE /api/v1/account/providers/google")).toHaveLength(0);
  });

  it("links: asks the server to start, then leaves for the provider and stays busy", async () => {
    const leave = vi.spyOn(browser, "leaveFor").mockImplementation(() => {});
    const { calls } = mount({
      routes: {
        "POST /api/v1/account/providers/corp/link": () =>
          json({ redirect_url: "https://login.corp.example/authorize?state=s" }),
      },
    });
    const button = within(await item("Corp SSO")).getByRole("button", { name: "Link Corp SSO" });
    await userEvent.click(button);
    await waitFor(() =>
      expect(leave).toHaveBeenCalledWith("https://login.corp.example/authorize?state=s"),
    );
    const [[, init]] = calls("POST /api/v1/account/providers/corp/link") as [[string, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ return_to: "/account?tab=sign-in" });
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it.each([
    [409, "provider_linked", "Corp SSO is already linked to this account.", true],
    [404, "unknown_provider", "Corp SSO is no longer offered by this server.", true],
    [
      429,
      "provider_unavailable",
      "Corp SSO can't be reached right now. Try again in a moment.",
      false,
    ],
    [401, "unauthenticated", "Your session has ended. Sign in again", false],
    [500, "internal", "Something went wrong on the server (500). Try again in a moment.", false],
  ])("explains a refused link start (%i %s)", async (status, code, message, refetches) => {
    const leave = vi.spyOn(browser, "leaveFor");
    const { calls } = mount({
      routes: { "POST /api/v1/account/providers/corp/link": () => refusal(status, code) },
    });
    const button = within(await item("Corp SSO")).getByRole("button", { name: "Link Corp SSO" });
    await userEvent.click(button);
    await waitFor(() =>
      expect(document.getElementById("providers-alert")).toHaveTextContent(message),
    );
    if (status === 401) {
      expect(screen.getByRole("link", { name: "Sign in again" })).toHaveAttribute(
        "href",
        "/sign-in",
      );
    }
    await waitFor(() =>
      expect(calls("GET /api/v1/account/providers")).toHaveLength(refetches ? 2 : 1),
    );
    expect(leave).not.toHaveBeenCalled();
    // Focus stays where it was; the button is usable again.
    expect(button).toHaveFocus();
    expect(button).not.toHaveAttribute("aria-busy");
  });

  it("says so when the server cannot be reached for a link", async () => {
    mount({
      routes: {
        "POST /api/v1/account/providers/corp/link": () => Promise.reject(new TypeError("offline")),
      },
    });
    await userEvent.click(
      within(await item("Corp SSO")).getByRole("button", { name: "Link Corp SSO" }),
    );
    await waitFor(() =>
      expect(document.getElementById("providers-alert")).toHaveTextContent(
        "Can't reach the server. Check your connection and try again.",
      ),
    );
  });

  it("unlinks after a confirmation, then lands on the row's new action", async () => {
    const success = vi.spyOn(toast, "success");
    const after = {
      has_password: false,
      providers: [
        google,
        { ...github, linked: false, linked_at: null, can_link: true, can_unlink: false },
        corp,
        old,
      ],
    };
    const { calls } = mount({
      routes: { "DELETE /api/v1/account/providers/gh": () => json(after) },
    });
    const user = userEvent.setup();
    const unlinkButton = within(await item("GitHub")).getByRole("button", {
      name: "Unlink GitHub",
    });

    // Cancel first: nothing is sent and focus goes back to the button.
    await user.click(unlinkButton);
    const dialog = await screen.findByRole("alertdialog", { name: "Unlink GitHub?" });
    expect(dialog).toHaveAccessibleDescription(/no longer be able to sign in with GitHub/);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(unlinkButton).toHaveFocus();
    expect(calls("DELETE /api/v1/account/providers/gh")).toHaveLength(0);

    await user.click(unlinkButton);
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Unlink" }),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(calls("DELETE /api/v1/account/providers/gh")).toHaveLength(1);
    expect(success).toHaveBeenCalledWith("GitHub unlinked", expect.anything());
    const gh = await item("GitHub");
    expect(gh).toHaveTextContent("Not linked");
    await waitFor(() =>
      expect(within(gh).getByRole("button", { name: "Link GitHub" })).toHaveFocus(),
    );
  });

  it.each([
    [409, "last_sign_in_method", "GitHub is your only way to sign in, so it can't be unlinked."],
    [404, "provider_not_linked", "GitHub was not linked any more."],
  ])("explains a refused unlink inside the dialog (%i %s)", async (status, code, message) => {
    const { calls } = mount({
      routes: { "DELETE /api/v1/account/providers/gh": () => refusal(status, code) },
    });
    const user = userEvent.setup();
    await user.click(within(await item("GitHub")).getByRole("button", { name: "Unlink GitHub" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Unlink" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(message);
    // The list on screen was out of date: it is read again.
    await waitFor(() => expect(calls("GET /api/v1/account/providers")).toHaveLength(2));
  });

  it("announces a finished link once and drops it from the URL", async () => {
    const success = vi.spyOn(toast, "success");
    const seen = vi.fn();
    const { calls, view, client } = mount({ props: { linked: "gh", onLinkResultSeen: seen } });
    await waitFor(() => expect(seen).toHaveBeenCalledTimes(1));
    expect(success).toHaveBeenCalledWith(
      "GitHub linked",
      expect.objectContaining({ description: "You can now sign in with GitHub.", id: "linked-gh" }),
    );
    await list();
    // The URL lost the parameter: rendering without it says nothing more.
    view.rerender(
      <QueryClientProvider client={client}>
        <SignInSettings onLinkResultSeen={seen} />
      </QueryClientProvider>,
    );
    expect(seen).toHaveBeenCalledTimes(1);
    expect(success).toHaveBeenCalledTimes(1);
    expect(calls("GET /api/v1/account/providers").length).toBeGreaterThanOrEqual(1);
  });

  it("does not trust ?linked= to name a provider", async () => {
    const success = vi.spyOn(toast, "success");
    mount({ props: { linked: "<b>evil</b>", onLinkResultSeen: vi.fn() } });
    await waitFor(() =>
      expect(success).toHaveBeenCalledWith("Sign-in provider linked", expect.anything()),
    );
    expect(success.mock.calls[0]?.[1]).not.toHaveProperty("description");
  });

  it.each([
    ["identity_linked_elsewhere", /already linked to another ExactDocs account/],
    ["provider_linked", /already has an identity of that provider/],
    ["not_allowed", /not in a group allowed to use this server/],
    ["not_linked", /could not be linked to this account/],
    ["sign_in_failed", /link could not be completed/],
    ["sign_in_cancelled", /did not confirm the link/],
    ["unauthenticated", /session ended before the link finished/],
    ["provider_unavailable", /can't be reached right now/],
    ["you won a prize", /^The link could not be completed/],
  ])(
    "explains a refused link (?link_error=%s), then drops it from the URL",
    async (code, message) => {
      const seen = vi.fn();
      const { view, client } = mount({ props: { linkError: code, onLinkResultSeen: seen } });
      await waitFor(() =>
        expect(document.getElementById("providers-alert")).toHaveTextContent(message),
      );
      expect(screen.queryByText(/prize/)).not.toBeInTheDocument();
      expect(seen).toHaveBeenCalledTimes(1);
      view.rerender(
        <QueryClientProvider client={client}>
          <SignInSettings onLinkResultSeen={seen} />
        </QueryClientProvider>,
      );
      // The alert stays until the next attempt; the URL is clean.
      expect(document.getElementById("providers-alert")).toHaveTextContent(message);
      expect(seen).toHaveBeenCalledTimes(1);
    },
  );

  it("offers a way back in when the session ended during the link", () => {
    expect(explainLinkError("unauthenticated")?.link).toEqual({
      href: "/sign-in",
      label: "Sign in again",
    });
    expect(explainLinkError(undefined)).toBeUndefined();
  });

  it("says when the list cannot be read, and tries again", async () => {
    let fail = true;
    mount({
      routes: {
        "GET /api/v1/account/providers": () => (fail ? refusal(500, "internal") : json(LIST)),
      },
    });
    expect(await screen.findByText("Couldn't load your sign-in providers.")).toHaveAttribute(
      "role",
      "alert",
    );
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await list()).toBeInTheDocument();
  });

  it("shows no section on a server without providers", async () => {
    const { calls } = mount({
      session: { ...signedIn, providers: [] },
      routes: {
        "GET /api/v1/account/providers": () => json({ has_password: true, providers: [] }),
      },
    });
    await waitFor(() => expect(calls("GET /api/v1/account/providers")).toHaveLength(1));
    expect(screen.queryByRole("heading", { name: "Linked sign-in providers" })).toBeNull();
  });
});

describe("Linked sign-in providers in Polish", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    act(() => resetPreferences());
  });

  it("lists, confirms and explains in Polish", async () => {
    setPreferences({ language: "pl" });
    mount({
      props: { linkError: "identity_linked_elsewhere", onLinkResultSeen: vi.fn() },
      routes: {
        "DELETE /api/v1/account/providers/gh": () => refusal(409, "last_sign_in_method"),
      },
    });
    expect(
      screen.getByRole("heading", { name: "Powiązani dostawcy logowania" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(document.getElementById("providers-alert")).toHaveTextContent(
        /już powiązana z innym kontem ExactDocs/,
      ),
    );
    const rows = await screen.findByRole("list", { name: "Dostawcy logowania" });
    expect(rows).toHaveTextContent("Utworzono nim konto");
    expect(rows).toHaveTextContent(/Powiązano · od 3 lis 2026/);
    expect(rows).toHaveTextContent("Niepowiązany");
    expect(rows).toHaveTextContent("Ten serwer już go nie oferuje");
    expect(within(rows).getByRole("button", { name: "Powiąż konto Corp SSO" })).toBeInTheDocument();
    expect(within(rows).getByRole("button", { name: "Odłącz Google" })).toHaveAccessibleDescription(
      /To Twój jedyny sposób logowania/,
    );
    const user = userEvent.setup();
    await user.click(within(rows).getByRole("button", { name: "Odłącz GitHub" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Odłączyć GitHub?" });
    await user.click(within(dialog).getByRole("button", { name: "Odłącz" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Logowanie przez GitHub to Twój jedyny sposób logowania, więc nie można go odłączyć.",
    );
  });

  it("names the providers and explains not_linked on the sign-in page in Polish", () => {
    setPreferences({ language: "pl" });
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <SignInPage error="not_linked" providers={configured} onSignedIn={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("link", { name: "Zaloguj się przez Google" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      /nie jest powiązana z żadnym kontem na tym serwerze/,
    );
  });
});
