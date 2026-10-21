import { defineConfig } from "@playwright/test";

// Runs the installed Chrome and Edge. Firefox runs through web-ext: npm run test:firefox.
// npm test runs each browser in its own Playwright process: a second browser launched
// in the same process intermittently left the extension's service worker stuck before
// it ran (Chrome and Edge 155, Playwright 1.63).
export default defineConfig({
  testDir: "tests",
  testMatch: "*.spec.js",
  timeout: 120_000,
  workers: 1, // every project shares the one companion pipe
  projects: [
    { name: "chrome", use: { channel: "chrome" } },
    { name: "msedge", use: { channel: "msedge" } },
  ],
});
