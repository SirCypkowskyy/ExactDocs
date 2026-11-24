import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_PREFERENCES, resetPreferences } from "@/shared/lib/preferences";
import { createAppRouter } from "./router";

/* Coming back from a provider link (#506) and the leaderboard opt-in (#510), through the router. */

const json = (body: unknown, status = 200) => Response.json(body, { status });
const account = { id: "1", username: "ada", role: "member", has_password: true };
const session = {
  state: "signed_in",
  account,
  providers: [{ name: "gh", display_name: "GitHub", icon: "github" }],
};
const providers = {
  has_password: true,
  providers: [
    {
      name: "gh",
      display_name: "GitHub",
      icon: "github",
      icon_url: null,
      configured: true,
      linked: true,
      origin: false,
      linked_at: "2026-11-24T08:00:00Z",
      last_signed_in_at: "2026-11-24T08:00:00Z",
      can_link: false,
      can_unlink: true,
    },
  ],
};

function api(url: string, init?: RequestInit) {
  if (url.endsWith("/session")) return json(session);
  if (url.endsWith("/account/providers")) return json(providers);
  if (url.endsWith("/stats/settings"))
    return json({ people_leaderboard: false, retention_months: 13 });
  if (url.endsWith("/account/preferences")) {
    return json({
      saved: true,
      preferences: init?.method === "PUT" ? JSON.parse(String(init.body)) : DEFAULT_PREFERENCES,
    });
  }
  if (url.includes("/tokens?")) return json({ tokens: [], next_cursor: null, total: 0 });
  return json({ error: "not_found" }, 404);
}

function mount(path: string) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => api(url, init)),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: [path] }));
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("Account after a provider link", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    resetPreferences();
  });

  it("opens the Sign-in tab, says the link worked, and drops ?linked= from the URL", async () => {
    const success = vi.spyOn(toast, "success");
    const router = mount("/account?tab=sign-in&linked=gh");
    expect(await screen.findByRole("tab", { name: "Sign-in" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitFor(() => expect(router.state.location.search).toEqual({ tab: "sign-in" }));
    expect(success).toHaveBeenCalledWith("GitHub linked", expect.anything());
    expect(success).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("list", { name: "Sign-in providers" })).toHaveTextContent(
      "GitHub",
    );
  });

  it("explains a refused link, keeps saying it, and drops ?link_error= from the URL", async () => {
    // The server's default return address has no tab: the result still lands on Sign-in.
    const router = mount("/account?link_error=identity_linked_elsewhere");
    await waitFor(() => expect(router.state.location.search).toEqual({ tab: "sign-in" }));
    expect(screen.getByRole("tab", { name: "Sign-in" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() =>
      expect(document.getElementById("providers-alert")).toHaveTextContent(
        /already linked to another ExactDocs account/,
      ),
    );
  });

  it("ignores a link result too long to be one", async () => {
    const router = mount(`/account?link_error=${"x".repeat(101)}`);
    expect(await screen.findByRole("tab", { name: "API tokens" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // Nothing is said, and the tab stays the default.
    expect(document.getElementById("providers-alert")).toBeNull();
    expect(router.state.location.search).not.toHaveProperty("tab");
  });

  it("offers the leaderboard opt-in on the Interface tab of a signed-in account", async () => {
    mount("/account?tab=interface");
    const optIn = await screen.findByRole("switch", { name: "Show me on the leaderboard" });
    await waitFor(() => expect(optIn).toBeEnabled());
    await waitFor(() => expect(optIn).toHaveAccessibleDescription(/leaderboard is off/));
    await userEvent.click(optIn);
    expect(optIn).toBeChecked();
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("switch", { name: "Underline links" })).toBeInTheDocument();
  });
});
