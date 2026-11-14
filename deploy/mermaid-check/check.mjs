// Parses every ```mermaid block in the project's Markdown (README, docs/, web/README.md, ...) and
// fails on a syntax error. It also fails on box-drawing "ASCII art" outside a mermaid block, so
// diagrams stay Mermaid. Run from the repo root: `pnpm --dir deploy/mermaid-check check`.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { JSDOM } from "jsdom";

const root = resolve(import.meta.dirname, "../..");
// mermaid needs a DOM only to sanitise labels; jsdom is enough to parse.
const dom = new JSDOM("<!doctype html><body></body>");
globalThis.window = dom.window;
globalThis.document = dom.window.document;
const { default: mermaid } = await import("mermaid");

const files = execFileSync("git", ["ls-files", "--cached", "--others", "--exclude-standard", "*.md"], { cwd: root, encoding: "utf8" })
  .split("\n")
  .filter((f) => f && !/(^|\/)(tests|fixtures|node_modules)\//.test(f) && !f.startsWith("web/src/"));
const BOX = /[─-╿▲▼]/;

let blocks = 0;
const errors = [];
for (const file of files) {
  const lines = readFileSync(resolve(root, file), "utf8").split("\n");
  let fence = null; // { indent, ticks, mermaid, start, body }
  for (const [i, line] of lines.entries()) {
    const open = fence ? null : line.match(/^(\s*)(`{3,}|~{3,})\s*(\S*)/);
    if (open) {
      fence = { indent: open[1].length, mark: open[2], mermaid: open[3] === "mermaid", start: i + 1, body: [] };
      continue;
    }
    if (fence && line.trim() === fence.mark) {
      if (fence.mermaid) {
        blocks += 1;
        const src = fence.body.map((l) => l.slice(Math.min(fence.indent, l.length))).join("\n");
        try {
          await mermaid.parse(src);
        } catch (e) {
          errors.push(`${file}:${fence.start}: ${String(e.message).split("\n").slice(0, 3).join(" | ")}`);
        }
      }
      fence = null;
      continue;
    }
    if (fence) fence.body.push(line);
    if (!fence?.mermaid && BOX.test(line)) errors.push(`${file}:${i + 1}: ASCII art; use a Mermaid diagram`);
  }
  if (fence) errors.push(`${file}:${fence.start}: unclosed code fence`);
}

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log(`${blocks} Mermaid diagrams in ${files.length} Markdown files parse`);
