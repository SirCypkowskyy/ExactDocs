// Bundle size of dist/ in one fixed definition, so PRs can be compared: run after `vite build`.
// Prints entry JS (the module script index.html loads), all JS and all CSS, raw and gzip, in kB.
import { readdirSync, readFileSync } from "node:fs";
import { extname, join } from "node:path";
import { gzipSync } from "node:zlib";

const dist = process.argv[2] ?? "dist";
const names = readdirSync(join(dist, "assets"));
const html = readFileSync(join(dist, "index.html"), "utf8");
const kb = (n) => (n / 1000).toFixed(1).padStart(8);
const rows = {
  "entry JS": names.filter((n) => extname(n) === ".js" && html.includes(`/assets/${n}`)),
  "all JS": names.filter((n) => extname(n) === ".js"),
  "all CSS": names.filter((n) => extname(n) === ".css"),
};
for (const [label, list] of Object.entries(rows)) {
  let raw = 0;
  let gzip = 0;
  for (const name of list) {
    const body = readFileSync(join(dist, "assets", name));
    raw += body.length;
    gzip += gzipSync(body).length;
  }
  console.log(`${label.padEnd(9)} ${kb(raw)} kB raw ${kb(gzip)} kB gzip  (${list.length} files)`);
}
