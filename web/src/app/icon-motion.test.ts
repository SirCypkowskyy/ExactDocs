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

describe("press feedback", () => {
  // Every class string of the app, read as text (the sources, not the built CSS). By path from
  // the working directory (web/): the runner's import.meta.url is not a file URL here.
  const fs = process.getBuiltinModule("node:fs") as unknown as {
    readdirSync: (path: string, options: { recursive: true }) => string[];
    readFileSync: (path: string, encoding: "utf8") => string;
  };
  const dir = `${(globalThis as unknown as { process: { cwd: () => string } }).process.cwd()}/src/`;
  const sources = Object.fromEntries(
    fs
      .readdirSync(dir, { recursive: true })
      .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f))
      .map((f) => [f, fs.readFileSync(dir + f, "utf8")]),
  );

  it("scales a control on press only when motion is allowed, and animates the scale", () => {
    const presses = Object.entries(sources).flatMap(([file, text]) =>
      [...text.matchAll(/[\w:[\]=-]*active:scale-\[[\d.]+\]/g)].map(([cls]) => ({ file, cls })),
    );
    expect(presses.length).toBeGreaterThan(10);
    for (const { file, cls } of presses) {
      expect(cls, file).toMatch(/^motion-safe:active:scale-/);
    }
    // Tailwind's scale utilities set the `scale` property, which a `transform` transition misses
    // (a variant such as the band's inherits its button's transition, so per file).
    for (const file of new Set(presses.map((p) => p.file))) {
      expect(sources[file], file).toMatch(/transition-(transform|\[[^\]]*\bscale\b[^\]]*\])/);
    }
  });

  it("reads the person's reduced-motion choice, not only the system's", () => {
    expect(styles).toContain(
      "@custom-variant motion-safe (&:where(:root:not([data-reduce-motion]) *));",
    );
  });
});

describe("row links", () => {
  const layer = styles.slice(styles.indexOf("@layer components {"));

  it("stretch the title link over its row, below utilities like `absolute`", () => {
    const stretch = rules(layer).find((r) => r.selector === "[data-row-link-cell] a::after");
    expect(stretch?.body).toMatch(/position: absolute/);
    expect(stretch?.body).toMatch(/inset: 0/);
  });

  it("lift every other control of the row above the stretch", () => {
    const lift = rules(layer).find((r) => r.selector.startsWith("[data-row-link] :is("));
    expect(lift?.selector).toMatch(/\ba\b.*\bbutton\b.*\[data-state\]/);
    expect(lift?.selector).toContain(":not([data-row-link-cell] a)");
    expect(lift?.body).toMatch(/position: relative/);
    expect(lift?.body).toMatch(/z-index: 1/);
  });
});
