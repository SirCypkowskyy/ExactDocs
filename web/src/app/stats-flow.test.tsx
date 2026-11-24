import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAppRouter } from "./router";

const json = (body: unknown, status = 200) => Response.json(body, { status });
const admin = { state: "signed_in", account: { id: "1", username: "ada", role: "admin" } };
const member = { state: "signed_in", account: { id: "2", username: "bob", role: "user" } };
const counts = { reads: 0, searches: 0, answers: 0 };

/** An instance with nothing counted yet, and one library whose latest sync failed. */
function api(session: unknown) {
  return (url: string) => {
    const path = new URL(url, "http://x").pathname.replace("/api/v1", "");
    if (path === "/session") return json(session);
    if (path === "/stats/settings")
      return json({ people_leaderboard: false, retention_months: 13 });
    if (path === "/stats/leaderboard") {
      return json({
        subject: "libraries",
        metric: "reads",
        period: "week",
        start: "2026-11-23",
        end: "2026-11-29",
        previous_start: "2026-11-16",
        previous_end: "2026-11-22",
        total: 0,
        ranked: 0,
        entries: [],
        you: null,
      });
    }
    if (path === "/stats/jobs") return json({ bucket: "day", from: "", to: "", days: [] });
    if (path === "/stats/usage") {
      return json({
        period: "day",
        since: "",
        until: "",
        by: "none",
        total: counts,
        series: [],
        groups: [],
        groups_total: 0,
      });
    }
    if (path === "/ai/usage/history")
      return json({ scope: "instance", id: "", window: "day", first: "", last: "", entries: [] });
    if (path === "/ai/usage") return json({ at: "", llm_searches_per_minute: null, scopes: [] });
    if (path === "/libraries") {
      const failing = new URL(url, "http://x").searchParams.has("sync_state");
      return json({
        notice: "",
        libraries: failing
          ? [
              {
                id: "/acme/payments",
                title: "Payments",
                description: "",
                default_version: null,
                default_pinned: false,
                source_url: "",
                refs: [],
                version_count: 0,
                tags: [],
                last_imported_at: null,
                logo: null,
                article_count: 0,
              },
            ]
          : [],
        next_cursor: null,
        total: failing ? 1 : 0,
      });
    }
    return json({ error: "not_found" }, 404);
  };
}

function mount(path: string, session: unknown) {
  const handler = api(session);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => handler(url)),
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

describe("the overview and the leaderboard in the app", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the overview to an operator under Admin, and nothing to anyone else", async () => {
    mount("/overview", admin);
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    const panel = within(nav).getByRole("button", { name: "Admin" });
    expect(panel).toHaveAttribute("data-active", "true");
    await userEvent.click(panel);
    expect(await within(nav).findByRole("link", { name: /^Overview/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // The app's router writes a list as `a,b`: the link opens the jobs table already filtered.
    expect(
      await screen.findByRole("link", { name: "Failed jobs of /acme/payments" }),
    ).toHaveAttribute("href", "/jobs?library=%2Facme%2Fpayments&state=failed");
    cleanup();

    mount("/overview", member);
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });

  it("offers everyone the leaderboard under Tools", async () => {
    mount("/leaderboard", member);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Leaderboard" }),
    ).toBeInTheDocument();
    // The board arrives after the settings: wait for it rather than for its first frame.
    await waitFor(() =>
      expect(screen.getByText("Nothing read this week yet.")).toBeInTheDocument(),
    );
    const nav = screen.getByRole("navigation", { name: "Main" });
    const tools = within(nav).getByRole("button", { name: "Tools" });
    expect(tools).toHaveAttribute("data-active", "true");
    await userEvent.click(tools);
    expect(await within(nav).findByRole("link", { name: /^Leaderboard/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
