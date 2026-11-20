import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyTheme, readTheme, THEME_STORAGE_KEY } from "@/shared/lib/theme";
import indexHtml from "../../../index.html?raw";
import { ThemeSwitch } from "./theme-switch";

/** jsdom has no matchMedia: report the given system scheme (and no reduced-motion preference). */
function systemPrefers(scheme: "light" | "dark") {
  const listeners = new Set<() => void>();
  let current = scheme;
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      get matches() {
        return query === "(prefers-color-scheme: dark)" && current === "dark";
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

beforeEach(() => {
  localStorage.clear();
  root.className = "";
  root.removeAttribute("style");
  delete root.dataset.theme;
});
afterEach(() => {
  vi.unstubAllGlobals();
});

async function choose(name: "Light" | "Dark" | "System") {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /^Theme:/ }));
  await user.click(await screen.findByRole("menuitemradio", { name }));
}

describe("theme switch", () => {
  it("follows the system by default and says so", () => {
    systemPrefers("dark");
    applyTheme(readTheme());
    render(<ThemeSwitch />);
    expect(root).toHaveClass("dark");
    expect(screen.getByRole("button", { name: "Theme: System (dark)" })).toBeInTheDocument();
  });

  it("applies a choice at once, announces it as checked and remembers it", async () => {
    systemPrefers("light");
    render(<ThemeSwitch />);
    await choose("Dark");
    expect(root).toHaveClass("dark");
    expect(root.style.colorScheme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(screen.getByRole("button", { name: "Theme: Dark" })).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "Theme: Dark" }));
    expect(await screen.findByRole("menuitemradio", { name: "Dark" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("menuitemradio", { name: "Light" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("can be used with the keyboard alone", async () => {
    systemPrefers("dark");
    render(<ThemeSwitch />);
    const user = userEvent.setup();
    await user.tab();
    expect(screen.getByRole("button", { name: /^Theme:/ })).toHaveFocus();
    await user.keyboard("{Enter}");
    await screen.findByRole("menu");
    await user.keyboard("{End}");
    expect(screen.getByRole("menuitemradio", { name: "System" })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(screen.getByRole("menuitemradio", { name: "Light" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(root).not.toHaveClass("dark");
  });

  it("keeps following the system while System is chosen", async () => {
    const system = systemPrefers("light");
    render(<ThemeSwitch />);
    await choose("System");
    expect(root).not.toHaveClass("dark");
    act(() => system.change("dark"));
    expect(root).toHaveClass("dark");
    expect(screen.getByRole("button", { name: "Theme: System (dark)" })).toBeInTheDocument();
  });

  it("ignores the system once a fixed theme is chosen", async () => {
    const system = systemPrefers("light");
    render(<ThemeSwitch />);
    await choose("Light");
    act(() => system.change("dark"));
    expect(root).not.toHaveClass("dark");
  });

  it("falls back to System when the stored value is unknown", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readTheme()).toBe("system");
  });
});

describe("the script in index.html (before first paint)", () => {
  const script = indexHtml.match(/<script>([\s\S]*?)<\/script>/)?.[1] ?? "";
  const run = () => new Function(script)();

  it("sets the stored theme on <html>, so a reload keeps it", () => {
    systemPrefers("light");
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    run();
    expect(root).toHaveClass("dark");
    expect(root.style.colorScheme).toBe("dark");
  });

  it("uses the system preference when nothing is stored", () => {
    systemPrefers("dark");
    run();
    expect(root).toHaveClass("dark");
  });

  it("keeps light when light is stored on a dark system", () => {
    systemPrefers("dark");
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    run();
    expect(root).not.toHaveClass("dark");
    expect(root.style.colorScheme).toBe("light");
  });
});
