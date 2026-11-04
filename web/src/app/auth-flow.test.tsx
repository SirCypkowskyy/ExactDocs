import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAppRouter } from "./router";

const account = { id: "1", username: "ada", role: "admin" };
const json = (body: unknown, status = 200) => Response.json(body, { status });

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

function mount(path: string, handler: Handler) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => handler(url, init)),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: [path] }));
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { client, router };
}

const signedIn = { state: "signed_in", account };
const signedOut = { state: "signed_out" };
const libraries = { libraries: [] };

describe("the session guard", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends a signed-out visitor to sign-in and remembers where they were going", async () => {
    const { router } = mount("/account", (url) => json(url.endsWith("/session") ? signedOut : {}));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(router.state.location.search).toEqual({ next: "/account" });
  });

  it("sends everyone to setup on a fresh server", async () => {
    mount("/sign-in", () => json({ state: "setup_required" }));
    expect(await screen.findByRole("heading", { name: "Create the admin account" })).toBeVisible();
  });

  it("keeps a signed-in visitor out of the auth pages", async () => {
    mount("/sign-in", (url) => json(url.endsWith("/libraries") ? libraries : signedIn));
    expect(await screen.findByRole("heading", { name: "Libraries" })).toBeInTheDocument();
  });

  it("obeys the gate on unknown addresses before saying not found", async () => {
    mount("/nothing/here", () => json(signedOut));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows not found to a signed-in visitor", async () => {
    mount("/nothing/here", () => json(signedIn));
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });

  it("returns to sign-in when the session ends while a page is open", async () => {
    const { client, router } = mount("/account", () => json(signedIn));
    expect(await screen.findByRole("heading", { name: "Account" })).toBeInTheDocument();
    await act(async () => client.setQueryData(["session"], signedOut));
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    expect(router.state.location.search).toEqual({ next: "/account" });
  });

  it("signs out from the account page and lands on sign-in without a return address", async () => {
    const { router } = mount("/account", (_url, init) =>
      init?.method === "DELETE" ? new Response(null, { status: 204 }) : json(signedIn),
    );
    await screen.findByRole("heading", { name: "Account" });
    const { default: userEvent } = await import("@testing-library/user-event");
    // the header (hidden on phones by CSS) and the page both carry one
    await userEvent.click(
      screen.getAllByRole("button", { name: "Sign out" }).at(-1) as HTMLElement,
    );
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    expect(router.state.location.search).toEqual({});
  });
});

describe("route errors", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("offers a retry when the server cannot be reached", async () => {
    mount("/sign-in", () => {
      throw new TypeError("offline");
    });
    expect(await screen.findByRole("heading", { name: "Can't reach the server" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
    expect(document.title).toBe("Can't reach the server - ExactDocs");
  });

  it("sends a 401 from a page's own data to sign-in", async () => {
    const { router } = mount("/", (url) =>
      url.endsWith("/libraries")
        ? json({ error: "not_authenticated", detail: "no session", fields: [] }, 401)
        : json(signedIn),
    );
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
  });
});
