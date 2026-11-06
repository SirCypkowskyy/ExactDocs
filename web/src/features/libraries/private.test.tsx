import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { AddLibraryPage } from "./index";

const SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";
const HTTPS = "https://gitlab.example.com/acme/private";
const SSH = "git@gitlab.example.com:acme/private.git";
const TOKEN = ["typed", "access", "value"].join("-");
// Not a real key: only its shape counts. The body is what must never leak.
const KEY_BODY = "c2VjcmV0LWtleS1ib2R5LW5vdC1hLXJlYWwta2V5".repeat(3);
const KEY = [
  "-----BEGIN OPENSSH PRIVATE KEY-----",
  ...(KEY_BODY.match(/.{1,70}/g) ?? []),
  "-----END OPENSSH PRIVATE KEY-----",
].join("\n");
const FINGERPRINT = "SHA256:nThbg6kXUpJWGl7E1IGOCspRomTxdCARLviKw6E5SY8";
const REFS = {
  default_branch: "main",
  branches: [{ name: "main", commit_sha: SHA }],
  tags: [{ name: "v2.0.0", commit_sha: SHA }],
  truncated: false,
};

type Reply = { status: number; body: unknown };
interface Call {
  method: string;
  url: string;
  body: Record<string, unknown> | undefined;
}
const err = (status: number, error: string, detail = "x"): Reply => ({
  status,
  body: { error, detail, fields: [] },
});

function serve(routes: { check?: (body: Record<string, unknown>) => Reply } = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body });
      const reply = (r: Reply) => Response.json(r.body, { status: r.status });
      if (url.endsWith("/v1/repositories/check")) {
        return reply(
          routes.check?.(body) ?? {
            status: 200,
            body: {
              host: "gitlab",
              library_id: "/acme/private",
              default_branch: "main",
              host_key_fingerprint: String(body.url).startsWith("git@") ? FINGERPRINT : null,
            },
          },
        );
      }
      if (url.includes("/v1/repositories/refs")) return Response.json(REFS);
      if (url.endsWith("/v1/repositories/preview")) {
        return Response.json({
          ref: "main",
          ref_kind: "branch",
          commit_sha: SHA,
          files: ["docs/a.md"],
          total: 1,
          truncated: false,
          include_paths: null,
          exclude_paths: null,
          context7: null,
          context7_warning: null,
        });
      }
      if (url.endsWith("/v1/libraries") && method === "POST") {
        return reply({
          status: 201,
          body: {
            library_id: "/acme/private",
            ref: "main",
            ref_kind: "branch",
            commit_sha: SHA,
            job_id: "j1",
          },
        });
      }
      if (url.includes("/v1/jobs/j1")) {
        return Response.json({
          id: "j1",
          kind: "import",
          library: "/acme/private",
          version: "main",
          commit_sha: SHA,
          state: "succeeded",
          done: 1,
          total: 1,
          problems: [],
          error: null,
          created_at: "2026-11-01T10:00:00Z",
          started_at: "2026-11-01T10:00:01Z",
          finished_at: "2026-11-01T10:01:00Z",
        });
      }
      return new Response("{}", { status: 404 });
    }),
  );
  return calls;
}

function renderAdd() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TestRouter
        pages={{ "/": () => <p>Libraries home</p>, "/libraries/new": AddLibraryPage }}
        start="/libraries/new"
      />
    </QueryClientProvider>,
  );
  return queryClient;
}

/** Everything the query and mutation caches hold, as text: no secret may be in it. */
const cached = (queryClient: QueryClient) =>
  JSON.stringify([
    queryClient
      .getQueryCache()
      .getAll()
      .map((q) => [q.queryKey, q.state.data]),
    queryClient
      .getMutationCache()
      .getAll()
      .map((m) => [m.options.mutationKey, m.state.variables, m.state.data]),
  ]);

async function typeAddress(url: string) {
  await userEvent.type(await screen.findByLabelText("Repository address"), url);
}

const check = () => userEvent.click(screen.getByRole("button", { name: "Check repository" }));

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

describe("adding a private library", () => {
  it("sends a token with the check, the refs, the preview and the add, and never keeps it", async () => {
    const calls = serve();
    const queryClient = renderAdd();
    await typeAddress(HTTPS);
    await userEvent.click(screen.getByLabelText("This repository is private"));
    const secret = screen.getByLabelText("Access token");
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute("autocomplete", "off");
    await userEvent.type(secret, TOKEN);
    // Typed, it is only the input's property: no attribute, nothing in the markup.
    expect(secret).toHaveValue(TOKEN);
    expect(secret.getAttribute("value")).toBeNull();
    expect(document.documentElement.outerHTML).not.toContain(TOKEN);
    await check();
    expect(document.documentElement.outerHTML).not.toContain(TOKEN);

    expect(await screen.findByLabelText("Library ID")).toHaveValue("/acme/private");
    const picker = await screen.findByLabelText("Version to import");
    expect(within(picker).getByRole("option", { name: "v2.0.0" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() =>
      expect(screen.getAllByRole("status").some((s) => s.textContent === "1 file matches.")).toBe(
        true,
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    expect(await screen.findByRole("heading", { name: "Import" })).toBeInTheDocument();

    const credential = { kind: "token", token: TOKEN };
    const sent = (end: string) => calls.find((c) => c.url.endsWith(end))?.body;
    expect(sent("/v1/repositories/check")).toEqual({ url: HTTPS, credential });
    const refs = calls.filter((c) => c.url.includes("/v1/repositories/refs"));
    expect(refs).toEqual([
      { method: "POST", url: "/api/v1/repositories/refs", body: { url: HTTPS, credential } },
    ]);
    expect(sent("/v1/repositories/preview")).toMatchObject({ url: HTTPS, credential });
    expect(sent("/v1/libraries")).toMatchObject({ url: HTTPS, credential });
    // Never in a URL, a cache, or browser storage.
    expect(calls.some((c) => c.url.includes(TOKEN))).toBe(false);
    expect(cached(queryClient)).not.toContain(TOKEN);
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(TOKEN);
    expect(document.body.innerHTML).not.toContain(TOKEN);

    // Another library starts from empty boxes.
    await userEvent.click(await screen.findByRole("button", { name: "Add another" }));
    expect(screen.getByLabelText("This repository is private")).not.toBeChecked();
    await typeAddress(HTTPS);
    await userEvent.click(screen.getByLabelText("This repository is private"));
    expect(screen.getByLabelText("Access token")).toHaveValue("");
  });

  it("takes a deploy key file for an ssh address and shows the host key before the add", async () => {
    const calls = serve();
    renderAdd();
    await typeAddress(SSH);
    await userEvent.click(screen.getByLabelText("This repository is private"));
    expect(screen.queryByLabelText("Access token")).not.toBeInTheDocument();
    const input = document.getElementById("credential-file") as HTMLInputElement;
    await userEvent.upload(input, new File([`${KEY}\n`], "deploy_key"));
    expect(await screen.findByText("Key read from deploy_key.")).toBeInTheDocument();
    expect(screen.getByLabelText("Deploy key")).toHaveAttribute("type", "password");
    await check();

    expect(await screen.findByText(FINGERPRINT)).toBeInTheDocument();
    expect(screen.getByText(/Compare it with the fingerprint your git host publishes/));
    expect(calls.find((c) => c.url.endsWith("/v1/repositories/check"))?.body).toEqual({
      url: SSH,
      credential: { kind: "ssh_key", private_key: KEY },
    });
    expect(calls.some((c) => c.url.endsWith("/v1/libraries"))).toBe(false);
  });

  it("wraps a deploy key pasted on one line again", async () => {
    const calls = serve();
    renderAdd();
    await typeAddress(SSH);
    await userEvent.click(screen.getByLabelText("This repository is private"));
    // A password input keeps no line breaks.
    await userEvent.type(screen.getByLabelText("Deploy key"), KEY.replaceAll("\n", ""));
    await check();
    await screen.findByLabelText("Library ID");
    const body = calls.find((c) => c.url.endsWith("/v1/repositories/check"))?.body ?? {};
    const sent = (body.credential as { private_key: string }).private_key;
    expect(sent.split("\n")).toEqual([
      "-----BEGIN OPENSSH PRIVATE KEY-----",
      ...(KEY_BODY.match(/.{1,70}/g) ?? []),
      "-----END OPENSSH PRIVATE KEY-----",
    ]);
  });

  it("asks for a token when a repository wants a login, and focuses it", async () => {
    serve({ check: () => err(422, "repository_auth_required") });
    renderAdd();
    await typeAddress(HTTPS);
    await check();
    expect(await screen.findByText(/asks for a login. If it is private/)).toBeInTheDocument();
    expect(screen.getByLabelText("This repository is private")).toBeChecked();
    await waitFor(() => expect(screen.getByLabelText("Access token")).toHaveFocus());
    expect(screen.getByLabelText("Access token")).toHaveAttribute("aria-invalid", "true");
  });

  it("says a token was refused, without repeating it", async () => {
    serve({ check: () => err(422, "repository_auth_required") });
    renderAdd();
    await typeAddress(HTTPS);
    await userEvent.click(screen.getByLabelText("This repository is private"));
    await userEvent.type(screen.getByLabelText("Access token"), TOKEN);
    await check();
    expect(await screen.findByText(/refused this token/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(TOKEN);
  });

  it("explains a changed SSH host key in plain words", async () => {
    serve({ check: () => err(422, "host_key_changed") });
    renderAdd();
    await typeAddress(SSH);
    await userEvent.click(screen.getByLabelText("This repository is private"));
    await userEvent.type(screen.getByLabelText("Deploy key"), KEY);
    await check();
    const alert = await screen.findByRole("alert");
    await waitFor(() => expect(alert).toHaveTextContent(/different host key/));
    expect(alert).toHaveTextContent(/intercepting/);
    expect(alert).toHaveTextContent(/known_hosts/);
  });

  it("checks the boxes before sending anything", async () => {
    const calls = serve();
    renderAdd();
    await typeAddress(HTTPS);
    await userEvent.click(screen.getByLabelText("This repository is private"));
    await userEvent.type(screen.getByLabelText("Access token"), "two words");
    await check();
    expect(await screen.findByText(/one line without spaces/)).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Access token"));
    await userEvent.clear(screen.getByLabelText("Repository address"));
    await userEvent.type(screen.getByLabelText("Repository address"), "file:///srv/docs");
    await check();
    expect(await screen.findByText(/A token needs an https:\/\/ address/)).toBeInTheDocument();
    expect(calls).toEqual([]);
  });

  it("starts over when the token changes after a check", async () => {
    const calls = serve();
    renderAdd();
    await typeAddress(HTTPS);
    await userEvent.click(screen.getByLabelText("This repository is private"));
    await userEvent.type(screen.getByLabelText("Access token"), TOKEN);
    await check();
    expect(await screen.findByLabelText("Library ID")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Access token"), "x");
    expect(screen.queryByLabelText("Library ID")).not.toBeInTheDocument();
    await check();
    await screen.findByLabelText("Library ID");
    const checks = calls.filter((c) => c.url.endsWith("/v1/repositories/check"));
    expect(checks.at(-1)?.body).toEqual({
      url: HTTPS,
      credential: { kind: "token", token: `${TOKEN}x` },
    });
  });
});
