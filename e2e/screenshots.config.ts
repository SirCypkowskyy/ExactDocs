import { defineConfig } from "@playwright/test";

// `just screenshots` (screenshots.py) starts and seeds the server, then runs screenshots.ts.
const url = process.env.EXACTDOCS_URL;
if (!url) throw new Error("EXACTDOCS_URL is not set: run `just screenshots`");

export default defineConfig({
  testDir: ".",
  testMatch: "screenshots.ts",
  timeout: 600_000,
  workers: 1,
  reporter: "list",
  outputDir: "test-results/screenshots",
  use: {
    // The pictures show the address of the README's quick start, whatever port the run got: the
    // browser maps it to the server (the MCP config on the Account page prints the origin).
    baseURL: "http://localhost:3000",
    launchOptions: {
      args: [`--host-resolver-rules=MAP localhost:3000 127.0.0.1:${new URL(url).port}`],
    },
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    locale: "en-US",
    timezoneId: "UTC",
    reducedMotion: "reduce",
    trace: "retain-on-failure",
  },
});
