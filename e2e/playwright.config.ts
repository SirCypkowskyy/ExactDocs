import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  timeout: 90_000,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  outputDir: "test-results",
  use: {
    baseURL: process.env.EXACTDOCS_URL,
    // short, so reaching a section means scrolling
    viewport: { width: 1280, height: 420 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
