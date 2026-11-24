import { afterEach, describe, expect, it } from "vitest";
import {
  DEFAULT_PREFERENCES,
  normalizePreferences,
  readPreferences,
  resetPreferences,
  setPreferences,
} from "./preferences";

describe("interface preferences", () => {
  afterEach(() => resetPreferences());

  it("defaults the leaderboard opt-in to no (#510)", () => {
    expect(DEFAULT_PREFERENCES.leaderboard_opt_in).toBe(false);
    expect(normalizePreferences({}).leaderboard_opt_in).toBe(false);
  });

  it("takes only an explicit true as consent", () => {
    expect(normalizePreferences({ leaderboard_opt_in: true }).leaderboard_opt_in).toBe(true);
    for (const value of ["true", 1, "yes", null, undefined, {}]) {
      expect(normalizePreferences({ leaderboard_opt_in: value }).leaderboard_opt_in).toBe(false);
    }
  });

  it("keeps the opt-in with the other choices and drops it on reset", () => {
    setPreferences({ leaderboard_opt_in: true, theme: "dark" });
    expect(readPreferences()).toMatchObject({ leaderboard_opt_in: true, theme: "dark" });
    // The page itself does not change for it: it is not a look.
    expect(document.documentElement.dataset).not.toHaveProperty("leaderboard");
    resetPreferences();
    expect(readPreferences().leaderboard_opt_in).toBe(false);
  });

  it("reads choices stored before #510 with the opt-in off", () => {
    localStorage.setItem(
      "exactdocs-preferences",
      JSON.stringify({ ...DEFAULT_PREFERENCES, leaderboard_opt_in: undefined, theme: "dark" }),
    );
    expect(readPreferences()).toEqual({ ...DEFAULT_PREFERENCES, theme: "dark" });
  });
});
