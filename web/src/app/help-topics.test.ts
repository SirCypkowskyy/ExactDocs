import { describe, expect, it } from "vitest";
import { libraryHelp } from "@/features/browse";
import { jobsHelp, librariesHelp } from "@/features/libraries";
import { playgroundHelp } from "@/features/playground";
import { searchHelp } from "@/features/search";
import { accountHelp } from "@/features/tokens";
import { roleRulesHelp, usersHelp } from "@/features/users";

/*
 * The page tours point at parts of the page (`data-tour`) and at pages of the docs site. Both
 * live elsewhere, so a rename there would leave a step ringing nothing or linking to a 404.
 */

const topics = {
  librariesHelp,
  jobsHelp,
  libraryHelp,
  searchHelp,
  playgroundHelp,
  accountHelp,
  usersHelp,
  roleRulesHelp,
};

// The docs live outside the app and the source is read as text, so both come from disk; the
// app's types leave Node out (as in icon-motion.test.ts), so the functions needed are typed here.
type Fs = {
  existsSync: (path: string) => boolean;
  readFileSync: (path: string, encoding: "utf8") => string;
  readdirSync: (path: string, options: { recursive: true; encoding: "utf8" }) => string[];
};
const { process } = globalThis as unknown as {
  process: { getBuiltinModule: (id: "node:fs") => Fs };
};
const fs = process.getBuiltinModule("node:fs");
// This file's path (Vite serves a file outside its root as `/@fs/<path>`), up to web/.
const web = decodeURIComponent(new URL(import.meta.url).pathname)
  .replace(/^\/@fs/, "")
  .replace(/src\/app\/[^/]+$/, "");
const docsRoot = `${web}../docs/`;
const code = fs
  .readdirSync(`${web}src`, { recursive: true, encoding: "utf8" })
  .filter((file) => file.endsWith(".tsx") && !file.endsWith(".test.tsx"))
  .map((file) => fs.readFileSync(`${web}src/${file}`, "utf8"))
  .join("\n");

/** The heading ids the docs site builds: lowercase, punctuation dropped, spaces to hyphens. */
const slug = (heading: string) =>
  heading
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");

/** The Markdown behind a published path: `mcp/connect/` is `mcp/connect.md` or its `index.md`. */
function docsPage(path: string): string | undefined {
  const page = path.replace(/\/$/, "");
  const file = (page ? [`${page}.md`, `${page}/index.md`] : ["index.md"])
    .map((name) => docsRoot + name)
    .find((file) => fs.existsSync(file));
  return file && fs.readFileSync(file, "utf8");
}

describe.each(Object.entries(topics))("%s", (_, topic) => {
  it("has 3 to 6 steps, each with both languages", () => {
    expect(topic.steps.length).toBeGreaterThanOrEqual(3);
    expect(topic.steps.length).toBeLessThanOrEqual(6);
    for (const step of topic.steps) {
      expect(step.title.en && step.title.pl && step.body.en && step.body.pl).toBeTruthy();
    }
  });

  it("rings parts that exist in the UI", () => {
    for (const step of topic.steps) {
      if (step.target) expect(code, step.target).toContain(`data-tour="${step.target}"`);
    }
  });

  it("links to docs pages and headings that exist", () => {
    for (const step of topic.steps) {
      const [path = "", anchor] = step.guide.split("#");
      const page = docsPage(path);
      expect(page, step.guide).toBeDefined();
      if (page && anchor) {
        const headings = page
          .split("\n")
          .filter((line) => /^#{1,6} /.test(line))
          .map((line) => slug(line.replace(/^#+ /, "")));
        expect(headings, step.guide).toContain(anchor);
      }
    }
  });
});
