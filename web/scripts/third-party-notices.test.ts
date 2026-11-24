import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  collectPackages,
  NOTICES_FILE,
  renderNotices,
  thirdPartyNotices,
} from "./third-party-notices.ts";

type Files = Record<string, string>;

/** A project with a node_modules/ laid out as npm or pnpm resolve it. */
function project(manifest: object, packages: Record<string, { manifest: object; files?: Files }>) {
  const root = mkdtempSync(join(tmpdir(), "notices-"));
  writeFileSync(join(root, "package.json"), JSON.stringify(manifest));
  for (const [name, { manifest: pkg, files = {} }] of Object.entries(packages)) {
    const dir = join(root, "node_modules", name);
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "package.json"), JSON.stringify({ name, version: "1.0.0", ...pkg }));
    for (const [file, text] of Object.entries(files)) writeFileSync(join(dir, file), text);
  }
  return root;
}

const app = () =>
  project(
    { dependencies: { ui: "1" }, devDependencies: { linter: "1", bundler: "1" } },
    {
      ui: {
        manifest: {
          license: "MIT",
          dependencies: { helper: "1" },
          optionalDependencies: { "native-only": "1" },
        },
        files: { LICENSE: "MIT License\nCopyright (c) UI authors" },
      },
      helper: { manifest: { license: "ISC", author: "Helper Author <helper@example.invalid>" } },
      font: { manifest: { license: "OFL-1.1" }, files: { LICENSE: "SIL OPEN FONT LICENSE 1.1" } },
      linter: { manifest: { license: "MIT" }, files: { LICENSE: "linter licence" } },
      bundler: {
        manifest: { license: "MIT", dependencies: { "bundler-dep": "1" } },
        files: {
          "LICENSE.md":
            "# Bundler license\nMIT, bundler\n\n# Licenses of bundled dependencies\nlong",
        },
      },
      "bundler-dep": { manifest: { license: "MIT" }, files: { LICENSE: "bundler-dep licence" } },
    },
  );

describe("third-party notices", () => {
  it("lists the production dependencies, transitively, and the tools without theirs", () => {
    const names = collectPackages(app(), ["bundler"]).map((p) => p.name);

    expect(names).toEqual(["bundler", "helper", "ui"]);
  });

  it("fails when a production dependency is not installed", () => {
    const root = project({ dependencies: { gone: "1" } }, {});

    expect(() => collectPackages(root, [])).toThrow(/gone .* is not installed/);
  });

  it("reproduces each licence, and names the licence and author when no file ships", () => {
    const notices = renderNotices(collectPackages(app(), ["bundler"]));

    expect(notices).toContain("ui 1.0.0 (MIT)\n\nMIT License\nCopyright (c) UI authors");
    expect(notices).toContain("names the licence ISC and the author Helper Author.");
    expect(notices).not.toContain("helper@example.invalid");
    expect(notices).toContain("# Bundler license\nMIT, bundler\n");
    expect(notices).not.toContain("Licenses of bundled dependencies");
    expect(notices).toContain("Shadcnblocks.com");
  });

  it("fails the build when a bundled file's package is not listed, else emits the file", () => {
    const root = app();
    const plugin = thirdPartyNotices(root, ["bundler"]);
    const emitted: string[] = [];
    const context = {
      emitFile: (file: { fileName: string }) => emitted.push(file.fileName),
      error: (message: string) => {
        throw new Error(message);
      },
    };
    const generate = plugin.generateBundle as unknown as (
      this: typeof context,
      options: object,
      bundle: object,
    ) => void;
    const chunk = {
      type: "chunk",
      moduleIds: [
        "\0vite/preload-helper.js",
        join(root, "src/main.tsx"),
        join(root, "node_modules/ui/index.js"),
      ],
    };
    const font = { type: "asset", originalFileNames: ["node_modules/font/files/a.woff2"] };

    expect(() => generate.call(context, {}, { "index.js": chunk, "a.woff2": font })).toThrow(
      /^bundled but not in THIRD_PARTY_NOTICES\.txt: font@1\.0\.0\./,
    );
    expect(emitted).toEqual([]);

    generate.call(context, {}, { "index.js": chunk });
    expect(emitted).toEqual([NOTICES_FILE]);
  });
});
