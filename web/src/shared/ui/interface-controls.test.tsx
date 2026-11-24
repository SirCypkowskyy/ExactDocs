import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyPreferences,
  DEFAULT_PREFERENCES,
  PREFERENCES_STORAGE_KEY,
  readPreferences,
  setPreferences,
} from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import indexHtml from "../../../index.html?raw";
import { InterfaceMenu, LanguageMenu, TextSizeControl, ThemeButton } from "./interface-controls";
import { TooltipProvider } from "./tooltip";

/** jsdom has no matchMedia: report the given system scheme and motion preference. */
function system(scheme: "light" | "dark", reduce = false) {
  const listeners = new Set<() => void>();
  let current = scheme;
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      get matches() {
        if (query === "(prefers-color-scheme: dark)") return current === "dark";
        if (query === "(prefers-reduced-motion: reduce)") return reduce;
        return false;
      },
      media: query,
      addEventListener: (_: string, l: () => void) => listeners.add(l),
      removeEventListener: (_: string, l: () => void) => listeners.delete(l),
    })),
  );
  return {
    change(next: "light" | "dark") {
      current = next;
      for (const l of listeners) l();
    },
  };
}

const root = document.documentElement;
const stored = () => JSON.parse(localStorage.getItem(PREFERENCES_STORAGE_KEY) ?? "{}");

beforeEach(() => {
  localStorage.clear();
  root.className = "";
  root.removeAttribute("style");
  root.lang = "en";
  for (const key of Object.keys(root.dataset)) delete root.dataset[key];
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("interface preferences", () => {
  it("default to the system and apply nothing extra", () => {
    system("dark");
    applyPreferences(readPreferences());
    expect(root).toHaveClass("dark");
    expect(root.dataset.theme).toBe("system");
    expect(root.dataset.contrast).toBeUndefined();
    expect(root.style.fontSize).toBe("");
  });

  it("put every choice on <html> and remember it", () => {
    system("light");
    setPreferences({
      contrast: "more",
      text_scale: 125,
      text_spacing: "wide",
      motion: "reduced",
      font: "dyslexic",
      underline_links: true,
      large_targets: true,
    });
    expect(root.dataset.contrast).toBe("more");
    expect(root.style.fontSize).toBe("125%");
    expect(root.dataset.spacing).toBe("wide");
    expect(root.dataset.reduceMotion).toBe("");
    expect(root.dataset.font).toBe("dyslexic");
    expect(root.dataset.links).toBe("underline");
    expect(root.dataset.targets).toBe("large");
    expect(stored().text_scale).toBe(125);
  });

  it("reduce motion when the system asks, unless the person chose full motion", () => {
    system("light", true);
    applyPreferences(readPreferences());
    expect(root.dataset.reduceMotion).toBe("");
    setPreferences({ motion: "full" });
    expect(root.dataset.reduceMotion).toBeUndefined();
  });

  it("drop unknown values instead of applying them", () => {
    localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({ theme: "sepia", text_scale: 95 }),
    );
    expect(readPreferences()).toEqual(DEFAULT_PREFERENCES);
  });

  it("keep a theme chosen before #486, stored under the old key", () => {
    localStorage.setItem("exactdocs-theme", "dark");
    expect(readPreferences().theme).toBe("dark");
  });
});

describe("band controls", () => {
  it("step the text size and stop at the ends", async () => {
    system("light");
    render(
      <TooltipProvider>
        <TextSizeControl />
      </TooltipProvider>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Larger text" }));
    expect(root.style.fontSize).toBe("110%");
    for (let i = 0; i < 5; i++)
      await user.click(screen.getByRole("button", { name: "Larger text" }));
    expect(root.style.fontSize).toBe("150%");
    expect(screen.getByRole("button", { name: "Larger text" })).toBeDisabled();
  });

  it("toggle light and dark in one press, from what the page shows", async () => {
    const os = system("light");
    applyPreferences(readPreferences());
    render(
      <TooltipProvider>
        <ThemeButton />
      </TooltipProvider>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Dark theme" }));
    expect(root).toHaveClass("dark");
    expect(stored().theme).toBe("dark");
    act(() => os.change("light"));
    expect(root).toHaveClass("dark");
  });

  it("offer the other preferences in one menu, by keyboard", async () => {
    system("light");
    render(
      <TestRouter
        pages={{
          "/": () => (
            <TooltipProvider>
              <InterfaceMenu />
            </TooltipProvider>
          ),
          "/account": () => null,
        }}
      />,
    );
    const user = userEvent.setup();
    const trigger = await screen.findByRole("button", { name: "Interface and accessibility" });
    trigger.focus();
    await user.keyboard("{Enter}");
    const contrast = await screen.findByRole("menuitemcheckbox", { name: "More contrast" });
    await user.click(contrast);
    expect(root.dataset.contrast).toBe("more");
    expect(screen.getByRole("menuitem", { name: "All interface settings" })).toHaveAttribute(
      "href",
      "/account?tab=interface",
    );
  });
});

describe("language", () => {
  it("switches from the band, each language named in itself", async () => {
    system("light");
    render(
      <TooltipProvider>
        <LanguageMenu />
      </TooltipProvider>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Language: English" }));
    const polski = await screen.findByRole("menuitemradio", { name: "Polski" });
    expect(polski).toHaveAttribute("lang", "pl");
    await user.click(polski);
    expect(root.lang).toBe("pl");
    expect(stored().language).toBe("pl");
    expect(screen.getByRole("button", { name: "Język: Polski" })).toBeInTheDocument();
  });

  it("follows the browser's first supported language when left to the system", () => {
    vi.stubGlobal("navigator", { ...navigator, languages: ["de-DE", "pl-PL", "en"] });
    applyPreferences(readPreferences());
    expect(root.lang).toBe("pl");
    vi.stubGlobal("navigator", { ...navigator, languages: ["de-DE", "fr"] });
    applyPreferences(readPreferences());
    expect(root.lang).toBe("en");
  });
});

describe("the script in index.html (before first paint)", () => {
  const script = indexHtml.match(/<script>([\s\S]*?)<\/script>/)?.[1] ?? "";
  const run = () => new Function(script)();

  it("applies the stored choices, so a reload never flashes", () => {
    system("light");
    localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({ ...DEFAULT_PREFERENCES, theme: "dark", text_scale: 125, contrast: "more" }),
    );
    run();
    expect(root).toHaveClass("dark");
    expect(root.style.colorScheme).toBe("dark");
    expect(root.style.fontSize).toBe("125%");
    expect(root.dataset.contrast).toBe("more");
  });

  it("follows the system when nothing is stored", () => {
    system("dark", true);
    run();
    expect(root).toHaveClass("dark");
    expect(root.dataset.reduceMotion).toBe("");
  });

  it("sets the page language from the stored choice or the browser", () => {
    system("light");
    localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({ ...DEFAULT_PREFERENCES, language: "pl" }),
    );
    run();
    expect(root.lang).toBe("pl");
    localStorage.clear();
    root.lang = "en";
    vi.stubGlobal("navigator", { ...navigator, languages: ["pl-PL"] });
    run();
    expect(root.lang).toBe("pl");
  });

  it("reads the theme stored before #486", () => {
    system("dark");
    localStorage.setItem("exactdocs-theme", "light");
    run();
    expect(root).not.toHaveClass("dark");
  });
});
