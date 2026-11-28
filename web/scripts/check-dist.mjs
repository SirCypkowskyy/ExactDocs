// RUN-03: the built UI loads nothing from another origin. Reads dist/ (HTML, CSS, every JS chunk)
// and reports external URLs; run after `vite build` (it is part of `pnpm build`).
import { readdirSync, readFileSync } from "node:fs";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Strings that appear in the bundle but are never fetched: XML namespaces, React's error-code
// message, example placeholders in the add-library form, the dev API default.
const ALLOWED_IN_JS = [
  /^https?:\/\/www\.w3\.org\//,
  /^https:\/\/react\.dev\/errors/,
  /^https:\/\/github\.com\/(acme\/payments|owner\/repo)/,
  /^http:\/\/(localhost|exactdocs\.invalid)/,
  // highlight.js comments, never fetched
  /^https:\/\/github\.com\/highlightjs\/highlight\.js\//,
  // browse/render/urls.ts builds links and image URLs from the library's own source URL
  /^https:\/\/github\.com\/$/,
  /^https:\/\/raw\.githubusercontent\.com\/\$\{/,
  // Recharts' state libraries (the overview's lazy chart chunk): text of a thrown error, never fetched
  /^https:\/\/redux(-toolkit)?\.js\.org\/Errors\?code=\$\{/,
  /^https:\/\/bit\.ly\/3cXEKWf$/,
  // The footer's repository link, and the docs site the footer and the Help tours' "Read about this
  // in the guide" links open: followed by a click, never fetched
  /^https:\/\/github\.com\/SirCypkowskyy\/ExactDocs$/,
  /^https:\/\/sircypkowskyy\.github\.io\/ExactDocs\/$/,
];
// A host starts with a letter or digit: `"https://" + x` and `https://${x}` build one at run time.
const ABSOLUTE = /https?:\/\/[A-Za-z0-9][^\s"'`)\\<>]+/g;
// Markup and stylesheets must be self-contained: no absolute URL, no protocol-relative one.
const MARKUP_EXTERNAL = [
  ABSOLUTE,
  /(?:src|href)\s*=\s*["']?\/\/[^\s"'>]+/gi,
  /url\(\s*["']?\/\/[^\s)]+/gi,
  /@import\s+["']?\/\/[^\s;"']+/gi,
];

// Licence banners (`/*! tailwindcss ... https://tailwindcss.com */`) are not loaded.
const COMMENTS = /\/\*[\s\S]*?\*\/|<!--[\s\S]*?-->/g;

function* walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(path);
    else yield path;
  }
}

/** External URLs in a built directory, as `file: url` lines (empty when clean). */
export function findExternal(dir) {
  const found = [];
  for (const file of walk(dir)) {
    const kind = extname(file);
    if (![".html", ".css", ".js", ".mjs"].includes(kind)) continue; // fonts etc. are binary
    const text = readFileSync(file, "utf8");
    const urls =
      kind === ".js" || kind === ".mjs"
        ? (text.match(ABSOLUTE) ?? []).filter((u) => !ALLOWED_IN_JS.some((ok) => ok.test(u)))
        : MARKUP_EXTERNAL.flatMap((re) => text.replace(COMMENTS, "").match(re) ?? []);
    for (const url of urls) found.push(`${file}: ${url}`);
  }
  return found;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const dist = fileURLToPath(new URL("../dist", import.meta.url));
  const found = findExternal(dist);
  if (found.length) {
    console.error(`external URLs in the build:\n${found.join("\n")}`);
    process.exit(1);
  }
}
