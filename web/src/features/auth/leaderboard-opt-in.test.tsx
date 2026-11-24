import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_PREFERENCES,
  readPreferences,
  resetPreferences,
  setPreferences,
} from "@/shared/lib/preferences";
import { InterfaceSettings } from "@/shared/ui/interface-settings";
import { usePreferencesSync } from "./hooks/use-preferences-sync";
import { LeaderboardOptIn } from "./index";

/* Account → Interface → "Show me on the leaderboard" (#510). */

const account = { id: "1", username: "ada", role: "member", has_password: true };

function Sync({ on }: { on: boolean }) {
  usePreferencesSync(on);
  return null;
}

function mount({
  signedIn = true,
  board = false as boolean | "fails",
  saved = { saved: true, preferences: { ...DEFAULT_PREFERENCES, leaderboard_opt_in: false } },
  preferences = 200,
} = {}) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/v1/stats/settings") {
      return board === "fails"
        ? Response.json({ error: "internal" }, { status: 500 })
        : Response.json({ people_leaderboard: board, retention_months: 13 });
    }
    if (url === "/api/v1/account/preferences") {
      if (preferences !== 200) return Response.json({ error: "x" }, { status: preferences });
      if (init?.method === "PUT") {
        return Response.json({ saved: true, preferences: JSON.parse(String(init.body)) });
      }
      return Response.json(saved);
    }
    return Response.json({ error: "unexpected" }, { status: 500 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(
    ["session"],
    signedIn ? { state: "signed_in", account, providers: [] } : { state: "signed_out" },
  );
  const view = render(
    <QueryClientProvider client={client}>
      <Sync on={signedIn} />
      <InterfaceSettings>
        <LeaderboardOptIn />
      </InterfaceSettings>
    </QueryClientProvider>,
  );
  const puts = () =>
    fetchMock.mock.calls
      .filter(([, init]) => init?.method === "PUT")
      .map(([, init]) => JSON.parse(String(init?.body)));
  return { view, fetchMock, puts };
}

const optIn = () => screen.getByRole("switch", { name: "Show me on the leaderboard" });

describe("Show me on the leaderboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    act(() => resetPreferences());
  });

  it("is an account choice: nobody signed out is offered it", async () => {
    const { fetchMock, view } = mount({ signedIn: false });
    expect(screen.getByRole("switch", { name: "Underline links" })).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Show me on the leaderboard" })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalledWith("/api/v1/stats/settings", expect.anything());
    view.unmount();
  });

  it("says only counts are shown and that the board is off, and still saves the choice", async () => {
    const { puts, view } = mount({ board: false });
    await waitFor(() => expect(optIn()).toBeEnabled());
    expect(optIn()).not.toBeChecked();
    await waitFor(() =>
      expect(optIn()).toHaveAccessibleDescription(
        /Only counts are shown, never what you read or searched for\..*The people leaderboard is off on this server/,
      ),
    );
    await userEvent.click(optIn());
    expect(optIn()).toBeChecked();
    expect(readPreferences().leaderboard_opt_in).toBe(true);
    await waitFor(() => expect(puts()).toHaveLength(1), { timeout: 2000 });
    expect(puts()[0]).toMatchObject({ leaderboard_opt_in: true });
    view.unmount();
  });

  it("shows the account's answer, and says when the board is on", async () => {
    const { view } = mount({
      board: true,
      saved: { saved: true, preferences: { ...DEFAULT_PREFERENCES, leaderboard_opt_in: true } },
    });
    await waitFor(() => expect(optIn()).toBeChecked());
    await waitFor(() =>
      expect(optIn()).toHaveAccessibleDescription(/The people leaderboard is on\.$/),
    );
    view.unmount();
  });

  it("cannot be changed while the account's answer is unknown", async () => {
    // A leftover from someone else on this browser must not show as this person's choice.
    setPreferences({ leaderboard_opt_in: true });
    const { view } = mount({ preferences: 503 });
    await waitFor(() =>
      expect(optIn()).toHaveAccessibleDescription(/couldn't be loaded, so it can't be changed/),
    );
    expect(optIn()).toBeDisabled();
    expect(optIn()).not.toBeChecked();
    view.unmount();
  });

  it("leaves the board's state unsaid when the settings cannot be read", async () => {
    const { view } = mount({ board: "fails" });
    await waitFor(() => expect(optIn()).toBeEnabled());
    expect(optIn()).not.toHaveAccessibleDescription(/leaderboard is (on|off)/);
    view.unmount();
  });

  it("speaks Polish", async () => {
    setPreferences({ language: "pl" });
    const { view } = mount({
      board: false,
      saved: { saved: true, preferences: { ...DEFAULT_PREFERENCES, language: "pl" } },
    });
    const polish = () => screen.getByRole("switch", { name: "Pokazuj mnie w rankingu" });
    await waitFor(() => expect(polish()).toBeEnabled());
    await waitFor(() =>
      expect(polish()).toHaveAccessibleDescription(
        /Widać tylko liczby.*Ranking osób jest wyłączony na tym serwerze/,
      ),
    );
    view.unmount();
  });
});
