import { defineConfig } from "@playwright/test";

// Изолированный сервер тестов; не подключаемся к чужому сервису на занятом порту.
const port = Number(process.env.E2E_PORT ?? 8123);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Некорректный E2E_PORT');

export default defineConfig({
  webServer: {
    command: `npx --no-install serve . -l ${port}`,
    port,
    reuseExistingServer: false,
  },
  use: { baseURL: `http://localhost:${port}` },
  testDir: "./tests/e2e",
});
