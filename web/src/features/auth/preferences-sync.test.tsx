import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_PREFERENCES,
  type Preferences,
  readPreferences,
  resetPreferences,
  setPreferences,
} from "@/shared/lib/preferences";
import { usePreferencesSync, usePreferencesSyncStatus } from "./hooks/use-preferences-sync";

let shown = "";
function Sync() {
  usePreferencesSync(true);
  shown = usePreferencesSyncStatus();
  return null;
}

type Saved = { saved: boolean; preferences: Preferences };

function mount(remote: Saved) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    expect(url).toBe("/api/v1/account/preferences");
    if (init?.method === "PUT") {
      return Response.json({ saved: true, preferences: JSON.parse(String(init.body)) });
    }
    return Response.json(remote);
  });
  vi.stubGlobal("fetch", fetchMock);
  const view = render(<Sync />);
  const puts = () =>
    fetchMock.mock.calls
      .filter(([, init]) => init?.method === "PUT")
      .map(([, init]) => JSON.parse(String(init?.body)) as Preferences);
  return { view, fetchMock, puts };
}

describe("interface preferences follow the account (#487, #510)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    resetPreferences();
  });

  it("adopts the account's saved choices, the leaderboard opt-in included", async () => {
    const { puts, view } = mount({
      saved: true,
      preferences: { ...DEFAULT_PREFERENCES, theme: "dark", leaderboard_opt_in: true },
    });
    await waitFor(() => expect(shown).toBe("saved"));
    expect(readPreferences()).toMatchObject({ theme: "dark", leaderboard_opt_in: true });
    expect(puts()).toEqual([]);
    view.unmount();
  });

  it("never sends a browser's leftover opt-in for an account that saved nothing", async () => {
    // Someone before opted in on this computer; the account now signing in never did.
    setPreferences({ theme: "dark", leaderboard_opt_in: true });
    const { puts, view } = mount({ saved: false, preferences: DEFAULT_PREFERENCES });
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toMatchObject({ theme: "dark", leaderboard_opt_in: false });
    expect(readPreferences()).toMatchObject({ theme: "dark", leaderboard_opt_in: false });
    view.unmount();
  });

  it("saves every key, the opt-in included, after a change", async () => {
    const { puts, view } = mount({ saved: true, preferences: DEFAULT_PREFERENCES });
    await waitFor(() => expect(shown).toBe("saved"));
    setPreferences({ leaderboard_opt_in: true });
    await waitFor(() => expect(puts()).toHaveLength(1), { timeout: 2000 });
    expect(puts()[0]).toEqual({ ...DEFAULT_PREFERENCES, leaderboard_opt_in: true });
    await waitFor(() => expect(shown).toBe("saved"));
    view.unmount();
  });

  it("keeps the choices in this browser when the server does not store them", async () => {
    vi.stubGlobal("fetch", async () => Response.json({ error: "not_found" }, { status: 404 }));
    const view = render(<Sync />);
    await waitFor(() => expect(shown).toBe("unavailable"));
    view.unmount();
  });
});
