import { useSyncExternalStore } from "react";

/*
 * Interface preferences (#486, #487): what a person chose about how the UI looks and moves.
 *
 * They live in this browser (localStorage) until the person signs in; the auth feature then syncs
 * them with the copy saved to the account (`/api/v1/account/preferences`). Every choice is applied
 * to <html> as a class, a data attribute or the root font size, so CSS does the rest:
 *
 *   theme          .dark + color-scheme + data-theme
 *   contrast       data-contrast="more"
 *   text_scale     font-size: <n>% on <html> (every size in the UI is in rem)
 *   text_spacing   data-spacing="wide" (WCAG 1.4.12 values)
 *   motion         data-motion="reduced" | "full" (absent: follow the system), and
 *                  data-reduce-motion when motion is reduced either way (CSS reads this one)
 *   font           data-font="hyperlegible" | "dyslexic" | "system" (absent: the default face)
 *   underline_links data-links="underline"
 *   large_targets  data-targets="large" (44 px controls with a mouse too)
 *   language       lang="en" | "pl" (the strings themselves come from shared/lib/i18n.ts)
 *   library_logos  read by the components that show a library's logo or generic icon (#504)
 *   leaderboard_opt_in  not applied to the page: the person's consent to be shown by name on the
 *                  people leaderboard (#510). It belongs to the account, so the UI offers it only
 *                  while signed in, and the sync always takes the account's copy of it.
 *
 * index.html runs the same `applyPreferences` logic inline before first paint, so nothing flashes.
 */

export type Theme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";
export type Contrast = "standard" | "more";
export type TextSpacing = "standard" | "wide";
export type Motion = "system" | "reduced" | "full";
export type Font = "default" | "hyperlegible" | "dyslexic" | "system";
/** The languages the UI is written in. */
export type Language = "en" | "pl";
export type LanguageChoice = Language | "system";

export type Preferences = {
  theme: Theme;
  contrast: Contrast;
  text_scale: TextScale;
  text_spacing: TextSpacing;
  motion: Motion;
  font: Font;
  underline_links: boolean;
  large_targets: boolean;
  language: LanguageChoice;
  library_logos: boolean;
  /** Agrees to be shown by name on the people leaderboard while the operator has it on (#510). */
  leaderboard_opt_in: boolean;
};

const THEMES: readonly Theme[] = ["light", "dark", "system"];
export const TEXT_SCALES = [90, 100, 110, 125, 150] as const;
export type TextScale = (typeof TEXT_SCALES)[number];
const MOTIONS: readonly Motion[] = ["system", "reduced", "full"];
const FONTS: readonly Font[] = ["default", "hyperlegible", "dyslexic", "system"];

export const DEFAULT_PREFERENCES: Preferences = {
  theme: "system",
  contrast: "standard",
  text_scale: 100,
  text_spacing: "standard",
  motion: "system",
  font: "default",
  underline_links: false,
  large_targets: false,
  language: "system",
  library_logos: true,
  leaderboard_opt_in: false,
};

/** localStorage key; index.html reads the same key before first paint. Kept across sign-outs. */
export const PREFERENCES_STORAGE_KEY = "exactdocs-preferences";
/** The key the theme lived under before #486; read once so nobody loses their choice. */
const LEGACY_THEME_KEY = "exactdocs-theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

const oneOf = <T>(values: readonly T[], value: unknown, fallback: T): T =>
  values.includes(value as T) ? (value as T) : fallback;

/** Keeps only known keys with valid values; anything else falls back to the default. */
export function normalizePreferences(raw: unknown): Preferences {
  const v = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const d = DEFAULT_PREFERENCES;
  return {
    theme: oneOf(THEMES, v.theme, d.theme),
    contrast: oneOf<Contrast>(["standard", "more"], v.contrast, d.contrast),
    text_scale: oneOf<TextScale>(TEXT_SCALES, v.text_scale, d.text_scale),
    text_spacing: oneOf<TextSpacing>(["standard", "wide"], v.text_spacing, d.text_spacing),
    motion: oneOf(MOTIONS, v.motion, d.motion),
    font: oneOf(FONTS, v.font, d.font),
    underline_links: typeof v.underline_links === "boolean" ? v.underline_links : d.underline_links,
    large_targets: typeof v.large_targets === "boolean" ? v.large_targets : d.large_targets,
    language: oneOf<LanguageChoice>(["system", "en", "pl"], v.language, d.language),
    library_logos: typeof v.library_logos === "boolean" ? v.library_logos : d.library_logos,
    // Only an explicit `true` is consent; anything else is no.
    leaderboard_opt_in: v.leaderboard_opt_in === true,
  };
}

/** The stored choices, or the defaults when there are none (or storage is blocked). */
export function readPreferences(): Preferences {
  try {
    const stored = localStorage.getItem(PREFERENCES_STORAGE_KEY);
    if (stored) return normalizePreferences(JSON.parse(stored));
    const legacy = localStorage.getItem(LEGACY_THEME_KEY);
    return normalizePreferences({ theme: legacy });
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

const matches = (query: string) =>
  typeof window.matchMedia === "function" && window.matchMedia(query).matches;

const resolveTheme = (theme: Theme): ResolvedTheme =>
  theme === "system" ? (matches(DARK_QUERY) ? "dark" : "light") : theme;

/**
 * The language the UI speaks: the person's choice, or with "system" the browser's first language
 * the UI is written in (Polish for pl-PL, English for en-GB), English when there is none.
 */
export function resolveLanguage(choice: LanguageChoice): Language {
  if (choice !== "system") return choice;
  const tags =
    typeof navigator === "undefined" ? [] : (navigator.languages ?? [navigator.language]);
  for (const tag of tags) {
    const base = String(tag).toLowerCase().split("-")[0];
    if (base === "pl" || base === "en") return base;
  }
  return "en";
}

/** True when motion should be reduced: the person said so, or "system" and the OS says so. */
export function reducedMotion(prefs: Preferences = readPreferences()): boolean {
  if (prefs.motion === "reduced") return true;
  if (prefs.motion === "full") return false;
  return matches(REDUCED_MOTION_QUERY);
}

function setData(root: HTMLElement, name: string, value: string | null) {
  if (value === null) delete root.dataset[name];
  else root.dataset[name] = value;
}

/** Puts every preference on <html>. Pure DOM: safe to call on every change. */
export function applyPreferences(prefs: Preferences): void {
  const root = document.documentElement;
  const resolved = resolveTheme(prefs.theme);
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
  root.dataset.theme = prefs.theme;
  root.style.fontSize = prefs.text_scale === 100 ? "" : `${prefs.text_scale}%`;
  setData(root, "contrast", prefs.contrast === "more" ? "more" : null);
  setData(root, "spacing", prefs.text_spacing === "wide" ? "wide" : null);
  setData(root, "motion", prefs.motion === "system" ? null : prefs.motion);
  // What CSS reads: the person's choice first, the OS setting second.
  setData(root, "reduceMotion", reducedMotion(prefs) ? "" : null);
  setData(root, "font", prefs.font === "default" ? null : prefs.font);
  setData(root, "links", prefs.underline_links ? "underline" : null);
  setData(root, "targets", prefs.large_targets ? "large" : null);
  root.lang = resolveLanguage(prefs.language);
}

const listeners = new Set<() => void>();
/** Called after a change made in this tab, with where it came from. The account sync listens. */
type ChangeListener = (prefs: Preferences, source: "local" | "account") => void;
const changeListeners = new Set<ChangeListener>();

function store(prefs: Preferences) {
  try {
    localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(prefs));
    localStorage.removeItem(LEGACY_THEME_KEY);
  } catch {
    // Storage blocked (private mode, policy): the choice holds for this page only.
  }
  cached = null;
}

/** A theme switch cross-fades the page where the browser can; anything else applies at once. */
function withCrossFade(next: Preferences, change: () => void): void {
  if (reducedMotion(next) || typeof document.startViewTransition !== "function") {
    change();
    return;
  }
  document.documentElement.classList.add("theme-fade");
  const transition = document.startViewTransition(change);
  transition.finished.finally(() => document.documentElement.classList.remove("theme-fade"));
}

function commit(next: Preferences, source: "local" | "account") {
  const previous = readPreferences();
  store(next);
  if (previous.theme !== next.theme && resolveTheme(previous.theme) !== resolveTheme(next.theme)) {
    withCrossFade(next, () => applyPreferences(next));
  } else {
    applyPreferences(next);
  }
  for (const listener of listeners) listener();
  for (const listener of changeListeners) listener(next, source);
}

/** Stores and applies a change made by the person; every `usePreferences` re-renders. */
export function setPreferences(patch: Partial<Preferences>): void {
  commit(normalizePreferences({ ...readPreferences(), ...patch }), "local");
}

/** Replaces the choices with the copy saved to the account (after sign-in). */
export function adoptAccountPreferences(prefs: Preferences): void {
  commit(normalizePreferences(prefs), "account");
}

/** Back to the defaults (the reset button on the Interface tab). */
export function resetPreferences(): void {
  commit(DEFAULT_PREFERENCES, "local");
}

/** Listen for changes made in this tab. Returns the unsubscribe function. */
export function onPreferencesChange(listener: ChangeListener): () => void {
  changeListeners.add(listener);
  return () => changeListeners.delete(listener);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // "System" follows the operating system while the page is open.
  const media = typeof window.matchMedia === "function" ? window.matchMedia(DARK_QUERY) : null;
  const onSystemChange = () => {
    const prefs = readPreferences();
    if (prefs.theme === "system") {
      applyPreferences(prefs);
      cached = null;
      listener();
    }
  };
  // Another tab changed the choices.
  const onStorage = (event: StorageEvent) => {
    if (event.key !== PREFERENCES_STORAGE_KEY) return;
    cached = null;
    applyPreferences(readPreferences());
    listener();
  };
  const motionMedia =
    typeof window.matchMedia === "function" ? window.matchMedia(REDUCED_MOTION_QUERY) : null;
  const onMotionChange = () => applyPreferences(readPreferences());
  // The browser's languages changed while the page is open ("system" follows them).
  const onLanguageChange = () => {
    const prefs = readPreferences();
    if (prefs.language !== "system") return;
    applyPreferences(prefs);
    cached = null;
    listener();
  };
  media?.addEventListener("change", onSystemChange);
  motionMedia?.addEventListener("change", onMotionChange);
  window.addEventListener("storage", onStorage);
  window.addEventListener("languagechange", onLanguageChange);
  return () => {
    listeners.delete(listener);
    media?.removeEventListener("change", onSystemChange);
    motionMedia?.removeEventListener("change", onMotionChange);
    window.removeEventListener("storage", onStorage);
    window.removeEventListener("languagechange", onLanguageChange);
  };
}

type Snapshot = { prefs: Preferences; resolved: ResolvedTheme; language: Language };
let cached: Snapshot | null = null;
const SERVER_SNAPSHOT: Snapshot = {
  prefs: DEFAULT_PREFERENCES,
  resolved: "light",
  language: "en",
};

function snapshot(): Snapshot {
  const prefs = readPreferences();
  const resolved = resolveTheme(prefs.theme);
  const language = resolveLanguage(prefs.language);
  if (
    cached &&
    cached.resolved === resolved &&
    cached.language === language &&
    JSON.stringify(cached.prefs) === JSON.stringify(prefs)
  ) {
    return cached;
  }
  cached = { prefs, resolved, language };
  return cached;
}

/** The current choices, and the theme and language they resolve to now. */
export function usePreferences(): Snapshot {
  return useSyncExternalStore(subscribe, snapshot, () => SERVER_SNAPSHOT);
}
