import { defineConfig } from "@playwright/test";

// Порт можно переопределить: E2E_PORT=8001 npx playwright test
// (по умолчанию 8000 — как в CI)
const port = Number(process.env.E2E_PORT ?? 8000);

export default defineConfig({
  webServer: {
    command: `npx serve . -l ${port}`,
    port,
    reuseExistingServer: true,
  },
  use: { baseURL: `http://localhost:${port}` },
  testDir: "./tests/e2e",
});
