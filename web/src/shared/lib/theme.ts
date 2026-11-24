/*
 * The theme is one of the interface preferences (preferences.ts); this hook is the small view of it
 * the toaster needs.
 */
import { type ResolvedTheme, type Theme, usePreferences } from "./preferences";

/** The current choice and what it resolves to now. */
export function useTheme(): { theme: Theme; resolved: ResolvedTheme } {
  const { prefs, resolved } = usePreferences();
  return { theme: prefs.theme, resolved };
}
