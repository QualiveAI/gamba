import { defineConfig } from "@playwright/test";

export default defineConfig({
  webServer: {
    command: "npx serve -s . -l 8000",
    port: 8000,
    reuseExistingServer: true,
  },
  testDir: "./tests/e2e",
});