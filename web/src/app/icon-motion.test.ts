import { describe, expect, it } from "vitest";

// Read from disk: the test runner hands CSS imports over empty. The app's types leave Node out,
// so the one function needed is typed here.
type Fs = { readFileSync: (path: URL, encoding: "utf8") => string };
const { process } = globalThis as unknown as {
  process: { getBuiltinModule: (id: "node:fs") => Fs };
};
const read = (name: string) =>
  process.getBuiltinModule("node:fs").readFileSync(new URL(name, import.meta.url), "utf8");
const iconMotion = read("./icon-motion.css");
const styles = read("./styles.css");

/*
 * The motion contract of DESIGN.md ("Icons and motion", "Motion"): reduced motion (the person's
 * choice or the system's, both land on `data-reduce-motion`) turns every icon reaction off, and
 * anything that moves on its own in the page only moves without it.
 */

/** Every innermost `selector { declarations }` of a stylesheet, comments removed. */
function rules(css: string): { selector: string; body: string }[] {
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...plain.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selector = "", body = ""]) => ({
    selector: selector.replace(/\s+/g, " ").trim(),
    body,
  }));
}

/** A step inside @keyframes (`from`, `to`, `25%`): not a selector. */
const isKeyframeStep = (selector: string) =>
  /^(from|to|[\d.]+%)(\s*,\s*(from|to|[\d.]+%))*$/.test(selector);

const moves = (body: string) => /(^|[;\s])(transform|animation|transition)\s*:/.test(body);

describe("icon reactions", () => {
  const moving = rules(iconMotion).filter((r) => !isKeyframeStep(r.selector) && moves(r.body));

  it("are all switched off under reduced motion", () => {
    expect(moving.length).toBeGreaterThan(5);
    for (const rule of moving) {
      expect(rule.selector, rule.selector).toContain(":root:not([data-reduce-motion])");
    }
  });

  it("move by transform only, and come from the documented set", () => {
    const named = [...iconMotion.matchAll(/data-icon-motion="([a-z]+)"/g)].map(([, n]) => n);
    expect(new Set(named)).toEqual(
      new Set([
        "forward",
        "back",
        "out",
        "down",
        "up",
        "turn",
        "cog",
        "refresh",
        "tilt",
        "pop",
        "warn",
        "draw",
        "alert",
      ]),
    );
    for (const rule of moving) {
      expect(rule.body, rule.selector).not.toMatch(/\b(width|height|top|left|margin)\s*:/);
    }
  });
});

describe("the page's own motion", () => {
  it("turns travel into a fade, and spinning into breathing, under reduced motion", () => {
    const reduced = styles.slice(styles.indexOf(":root[data-reduce-motion] {"));
    expect(reduced).toMatch(/\.row-in,\s*\.rise\s*\{\s*animation: fade-in/);
    expect(reduced).toMatch(/\.spin,\s*\.sweep\s*\{\s*animation: breathe/);
  });

  it("zeroes the slide and zoom of dialogs, sheets and menus under reduced motion", () => {
    const rule = rules(styles).find((r) => r.selector === ":root[data-reduce-motion] [data-state]");
    expect(rule?.body).toMatch(/--tw-enter-scale: 1 !important/);
    expect(rule?.body).toMatch(/--tw-enter-translate-y: 0 !important/);
    expect(rule?.body).toMatch(/--tw-exit-scale: 1 !important/);
  });
});
