import { useSyncExternalStore } from "react";

/** What the person picked. "system" follows the operating system's color scheme. */
export type Theme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEMES: readonly Theme[] = ["light", "dark", "system"];
/** localStorage key; index.html reads the same key before first paint. Kept across sign-outs. */
export const THEME_STORAGE_KEY = "exactdocs-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

const isTheme = (value: unknown): value is Theme =>
  typeof value === "string" && (THEMES as readonly string[]).includes(value);

/** The stored choice, or "system" when there is none (or storage is blocked). */
export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

const systemPrefersDark = () =>
  typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;

const resolveTheme = (theme: Theme): ResolvedTheme =>
  theme === "system" ? (systemPrefersDark() ? "dark" : "light") : theme;

/** Puts the resolved theme on <html>: the `dark` class (Tailwind's variant) and `color-scheme`. */
export function applyTheme(theme: Theme): void {
  const resolved = resolveTheme(theme);
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
  root.dataset.theme = theme;
}

const listeners = new Set<() => void>();
const notify = () => {
  for (const listener of listeners) listener();
};

/** Applies the change with a short cross-fade where the browser can, at once otherwise. */
function withCrossFade(change: () => void): void {
  const reduced =
    typeof window.matchMedia === "function" && window.matchMedia(REDUCED_MOTION_QUERY).matches;
  if (reduced || typeof document.startViewTransition !== "function") {
    change();
    return;
  }
  document.documentElement.classList.add("theme-fade");
  const transition = document.startViewTransition(change);
  transition.finished.finally(() => document.documentElement.classList.remove("theme-fade"));
}

/** Stores and applies a choice; every `useTheme` re-renders. */
export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage blocked (private mode, policy): the choice holds for this page only.
  }
  withCrossFade(() => applyTheme(theme));
  notify();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // "System" follows the operating system while the page is open.
  const media = typeof window.matchMedia === "function" ? window.matchMedia(DARK_QUERY) : null;
  const onSystemChange = () => {
    if (readTheme() === "system") {
      applyTheme("system");
      listener();
    }
  };
  // Another tab changed the choice.
  const onStorage = (event: StorageEvent) => {
    if (event.key !== THEME_STORAGE_KEY) return;
    applyTheme(readTheme());
    listener();
  };
  media?.addEventListener("change", onSystemChange);
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    media?.removeEventListener("change", onSystemChange);
    window.removeEventListener("storage", onStorage);
  };
}

const snapshot = () => `${readTheme()}:${resolveTheme(readTheme())}`;

/** The current choice and what it resolves to now. */
export function useTheme(): { theme: Theme; resolved: ResolvedTheme } {
  const value = useSyncExternalStore(subscribe, snapshot, () => "system:light");
  const [theme, resolved] = value.split(":") as [Theme, ResolvedTheme];
  return { theme, resolved };
}
