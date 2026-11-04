import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findExternal } from "./check-dist.mjs";

// RUN-03: the checker `pnpm build` runs over dist/.
function dist(files) {
  const dir = mkdtempSync(join(tmpdir(), "dist-"));
  mkdirSync(join(dir, "assets"));
  for (const [name, text] of Object.entries(files)) writeFileSync(join(dir, name), text);
  return dir;
}

describe("check-dist", () => {
  it("passes a self-contained build", () => {
    const dir = dist({
      "index.html": '<script type="module" src="/assets/index.js"></script>',
      "assets/a.css": "@font-face{src:url(/assets/f.woff2)}",
      "assets/index.js":
        'const ns="http://www.w3.org/2000/svg";const e="https://react.dev/errors/1"',
    });
    expect(findExternal(dir)).toEqual([]);
  });

  it.each([
    ["index.html", '<link href="https://fonts.googleapis.com/css2" rel="stylesheet">'],
    ["index.html", '<script src="//cdn.example.com/x.js"></script>'],
    ["assets/a.css", '@import "//fonts.example.com/x.css";'],
    ["assets/a.css", "a{background:url(https://cdn.example.com/x.png)}"],
    ["assets/chunk.js", 'fetch("https://telemetry.example.com/ping")'],
  ])("fails %s with an external URL", (name, text) => {
    expect(findExternal(dist({ [name]: text }))).toHaveLength(1);
  });
});
