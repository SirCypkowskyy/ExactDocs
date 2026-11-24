/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { thirdPartyNotices } from "./scripts/third-party-notices.ts";

const apiTarget = process.env.EXACTDOCS_API_URL ?? "http://localhost:3000";

export default defineConfig({
  base: "/",
  plugins: [
    // Must come before the React plugin.
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    // dist/THIRD_PARTY_NOTICES.txt: the licences of what the bundle holds (#533).
    thirdPartyNotices(fileURLToPath(new URL(".", import.meta.url))),
  ],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      "/mcp": { target: apiTarget, changeOrigin: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // The busiest tests (user-event flows of a whole form) take ~1.5-2 s of CPU on an idle machine
    // and passed 5 s when the CPU was shared (the suite run beside CPU burners); the ~2.5 s polling
    // tests are mostly a deliberate 1.8 s wait. A ceiling, so passing tests are no slower.
    testTimeout: 15_000,
  },
});
