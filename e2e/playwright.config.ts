import { defineConfig } from "@playwright/test";

const baseURL = process.env.EXACTDOCS_URL;
if (!baseURL) throw new Error("EXACTDOCS_URL is not set: run the test through e2e/run.py");

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  timeout: 90_000,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  outputDir: "test-results",
  use: {
    baseURL,
    // short, so reaching a section means scrolling
    viewport: { width: 1280, height: 420 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
