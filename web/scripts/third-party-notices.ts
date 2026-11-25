// The web UI's third-party notices (#533). `vite build` writes dist/THIRD_PARTY_NOTICES.txt, which
// ships wherever the UI does: the exactdocs wheel (exactdocs/_web/), so `uvx exactdocs`, and the
// Docker image. It holds the licence of every package the production dependencies of package.json
// pull in (the fonts' SIL Open Font License among them), of the build tools whose code is in the
// bundle, and of the source adapted into src/. The build fails if a bundled package is missing.
import { existsSync, readdirSync, readFileSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join, sep } from "node:path";
import type { Plugin } from "vite";

export const NOTICES_FILE = "THIRD_PARTY_NOTICES.txt";

/** Build tools (devDependencies) whose code is in the bundle, without their own dependencies:
 * Tailwind CSS's generated stylesheet (its preflight among it) and Vite's module preload helper. */
const BUNDLED_TOOLS = ["tailwindcss", "vite"];

const LICENSE_FILE = /^(licen[cs]e|copying|notice)([.-].*)?$/i;
/** Where a tool's licence file goes on to its own bundled dependencies (Vite's LICENSE.md): the
 * bundle holds the tool's code only, so the notice stops there. */
const TOOL_DEPENDENCIES = /^#+ .*bundled dependencies/im;
const RULE = "-".repeat(79);

/** Source copied or adapted into src/ (not an npm package), with its terms. */
const ADAPTED_SOURCES = `shadcn/ui (https://ui.shadcn.com), MIT
The components in src/shared/ui/ start from shadcn/ui's.

MIT License

Copyright (c) 2023 shadcn

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

${RULE}
Shadcnblocks.com free blocks (https://www.shadcnblocks.com), not open source
Some layouts are adapted from these free blocks (web/DESIGN.md): "Application Shell 3" (the app
shell), "Login 2" (the sign-in and setup frame), "Blogpost 2" (the reader's contents column),
"Changelog 1" (the version rail) and "Data Table 1" (the server-side tables). The blocks are
copyrighted works of Shadcnblocks.com, used under its Terms & Conditions for free blocks
(https://www.shadcnblocks.com/terms), which allow installing and modifying them in an end product
and keeping them in that product's repository. ExactDocs' Apache-2.0 licence does not grant
rights in that material beyond those terms; in particular the blocks may not be republished
on their own as a library, kit, template or catalog.`;

type Package = {
  name: string;
  version: string;
  license: string;
  homepage?: string;
  author?: string;
  texts: string[];
};

type Manifest = {
  name?: string;
  version?: string;
  license?: string | { type?: string };
  homepage?: string;
  author?: string | { name?: string; email?: string };
  repository?: string | { url?: string };
  dependencies?: Record<string, string>;
  optionalDependencies?: Record<string, string>;
};

function readManifest(dir: string): Manifest {
  return JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
}

/** Node's lookup of `name` from `from`: the nearest node_modules/<name> upwards, real path. */
function resolvePackage(from: string, name: string): string | undefined {
  for (let dir = from; ; dir = dirname(dir)) {
    const candidate = join(dir, "node_modules", name);
    if (existsSync(join(candidate, "package.json"))) return realpathSync(candidate);
    if (dirname(dir) === dir) return undefined;
  }
}

function describePackage(dir: string, tool: boolean): Package {
  const manifest = readManifest(dir);
  const license = typeof manifest.license === "object" ? manifest.license.type : manifest.license;
  const repository =
    typeof manifest.repository === "object" ? manifest.repository.url : manifest.repository;
  const texts = readdirSync(dir)
    .filter((file) => LICENSE_FILE.test(file))
    .sort()
    .map((file) => readFileSync(join(dir, file), "utf8"))
    .map((text) => (tool ? text.split(TOOL_DEPENDENCIES)[0] : text).trim());
  // A name only: "Name <email> (url)" becomes "Name".
  const author = (typeof manifest.author === "object" ? manifest.author.name : manifest.author)
    ?.replace(/\s*[<(].*$/, "")
    .trim();
  return {
    name: manifest.name ?? dir,
    version: manifest.version ?? "0.0.0",
    license: license?.trim() || "UNKNOWN",
    homepage: manifest.homepage ?? repository,
    author: author || undefined,
    texts,
  };
}

/** The packages behind `root`'s production dependencies (transitively, optional ones when
 * installed) and the named `tools` (without theirs), sorted by name and version. */
export function collectPackages(root: string, tools: string[] = BUNDLED_TOOLS): Package[] {
  const found = new Map<string, Package>();
  const queue: [from: string, name: string, optional: boolean, follow: boolean][] = [
    ...Object.keys(readManifest(root).dependencies ?? {}).map(
      (name) => [root, name, false, true] as [string, string, boolean, boolean],
    ),
    ...tools.map((name) => [root, name, false, false] as [string, string, boolean, boolean]),
  ];
  for (let next = queue.shift(); next; next = queue.shift()) {
    const [from, name, optional, follow] = next;
    const dir = resolvePackage(from, name);
    if (!dir) {
      if (optional) continue;
      throw new Error(`third-party notices: ${name} (needed from ${from}) is not installed`);
    }
    if (found.has(dir)) continue;
    found.set(dir, describePackage(dir, !follow));
    if (!follow) continue;
    const manifest = readManifest(dir);
    for (const dep of Object.keys(manifest.dependencies ?? {})) queue.push([dir, dep, false, true]);
    for (const dep of Object.keys(manifest.optionalDependencies ?? {}))
      queue.push([dir, dep, true, true]);
  }
  return [...found.values()].sort(
    (a, b) => a.name.localeCompare(b.name) || a.version.localeCompare(b.version),
  );
}

/** The notices file: a header, the adapted source, then one section per package. */
export function renderNotices(packages: Package[]): string {
  const sections = packages.map((p) => {
    const head = `${p.name} ${p.version} (${p.license})${p.homepage ? `\n${p.homepage}` : ""}`;
    const body = p.texts.length
      ? p.texts.join(`\n\n`)
      : `The package ships no licence file; its package.json names the licence ${p.license}` +
        (p.author ? ` and the author ${p.author}.` : ".");
    return `${RULE}\n${head}\n\n${body}\n`;
  });
  return `Third-party notices for the ExactDocs web UI
${"=".repeat(44)}

The ExactDocs web UI (the files next to this one) contains code and fonts by the third parties
below, each under its own licence, reproduced here. ExactDocs itself is licensed under the Apache
License, Version 2.0 (LICENSE in the exactdocs distribution and the repository).

Generated by \`vite build\` (web/scripts/third-party-notices.ts) from the production dependencies
in web/package.json and the build tools whose code is in the bundle.

${RULE}
Source adapted into the UI
${RULE}
${ADAPTED_SOURCES}

${RULE}
Packages (${packages.length})
${sections.join("\n")}`;
}

/** The package that holds `file` inside node_modules: the nearest package.json with a name. */
function owningPackage(file: string): { name: string; version: string } | undefined {
  if (!file.includes(`${sep}node_modules${sep}`)) return undefined;
  for (let dir = dirname(file); dir.includes(`${sep}node_modules${sep}`); dir = dirname(dir)) {
    if (!existsSync(join(dir, "package.json"))) continue;
    const manifest = readManifest(dir);
    if (manifest.name) return { name: manifest.name, version: manifest.version ?? "0.0.0" };
  }
  return undefined;
}

/** Emits THIRD_PARTY_NOTICES.txt into the build, and fails it when a bundled module comes from
 * a package the notices leave out (say, a devDependency imported by the app). */
export function thirdPartyNotices(root: string, tools: string[] = BUNDLED_TOOLS): Plugin {
  return {
    name: "exactdocs:third-party-notices",
    apply: "build",
    generateBundle(_, bundle) {
      const packages = collectPackages(root, tools);
      const listed = new Set(packages.map((p) => `${p.name}@${p.version}`));
      const missing = new Set<string>();
      for (const output of Object.values(bundle)) {
        const ids = output.type === "chunk" ? output.moduleIds : (output.originalFileNames ?? []);
        for (const id of ids) {
          if (id.startsWith("\0")) continue;
          const owner = owningPackage(isAbsolute(id) ? id : join(root, id));
          if (owner && !listed.has(`${owner.name}@${owner.version}`))
            missing.add(`${owner.name}@${owner.version}`);
        }
      }
      if (missing.size)
        this.error(
          `bundled but not in ${NOTICES_FILE}: ${[...missing].sort().join(", ")}. Make it a ` +
            "production dependency in package.json, or add it to BUNDLED_TOOLS.",
        );
      this.emitFile({ type: "asset", fileName: NOTICES_FILE, source: renderNotices(packages) });
    },
  };
}
