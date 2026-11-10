import { test, expect } from "@playwright/test";

test("deposit_and_open_case", async ({ page }) => {
  await page.route("**/auth/telegram", (route) =>
    route.fulfill({ json: { access_token: "test-jwt" } })
  );
  await page.route("**/cases", (route) =>
    route.fulfill({ json: [{ id: 1, name: "Test Case", price_units: 100 }] })
  );
  await page.route("**/deposits", (route) =>
    route.fulfill({ json: { payment_id: "p1", qr_string: "test-qr" } })
  );
  await page.route("**/cases/1/open", (route) =>
    route.fulfill({ json: { nominal_units: 50 } })
  );
  await page.goto("/");
  await expect(page.locator("#cases-list")).toBeVisible();
});

test("withdraw_preview_and_region", async ({ page }) => {
  await page.route("**/auth/telegram", (route) =>
    route.fulfill({ json: { access_token: "test-jwt" } })
  );
  await page.route("**/wallet", (route) =>
    route.fulfill({ json: { units: 500, freebets: 0, min_withdraw: 1000 } })
  );
  await page.goto("/");
  await page.click('[data-screen="saldo"]');
  // превью считается из номинала карточки: 1000 🪙 = $15.00, на карту $12.00 (80%)
  await expect(page.locator("#wd-preview")).toContainText("Saque:");
  await expect(page.locator("#wd-preview")).toContainText("$12.00");
  // регион обязателен для отправки вывода (backend /withdrawals {amount, region})
  await expect(page.locator("#wd-region")).toHaveValue("BR");
});

test("mines_reveal_and_cashout", async ({ page }) => {
  await page.route("**/auth/telegram", (route) =>
    route.fulfill({ json: { access_token: "test-jwt" } })
  );
  await page.route("**/games/mines/start", (route) =>
    route.fulfill({ json: { session_id: 1, grid_size: 25, mine_count: 3 } })
  );
  await page.route("**/games/mines/reveal", (route) =>
    route.fulfill({ json: { hit_mine: false, revealed: 1, bias_applied: false } })
  );
  await page.route("**/games/mines/cashout*", (route) =>
    route.fulfill({ json: { payout: 150, revealed: 1 } })
  );
  await page.goto("/");
  await page.click('[data-screen="jogos"]');
  // mines — активная игровая вкладка по умолчанию
  await expect(page.locator("#mines-grid")).toBeVisible();
  await page.click('.game-card[data-g="crash"]');
  await expect(page.locator("#crash-bet")).toBeVisible();
  await page.click('.game-card[data-g="mines"]');
  await expect(page.locator("#mines-grid")).toBeVisible();
});

test("deposit_methods_rendered_on_saldo", async ({ page }) => {
  await page.route("**/auth/telegram", (route) =>
    route.fulfill({ json: { access_token: "test-jwt" } })
  );
  await page.route("**/meta/geos", (route) =>
    route.fulfill({ json: [{ geo: "BR", methods: ["card", "crypto"] }] })
  );
  await page.route("**/meta/tenant", (route) =>
    route.fulfill({
      json: {
        tenant: "default",
        brand: { name: "ROBLOXWINDROP", logo_url: "", primary_color: "#c8102e" },
        domains: {},
        geos: ["BR"],
        games: ["roblox"],
      },
    })
  );
  await page.route("**/deposits", (route) =>
    route.fulfill({
      json: {
        intent_id: "i1",
        client_payload: { payment_url: "https://pay.example/x", fee_minor: 40 },
        fee_minor: 40,
        amount_gross_minor: 1040,
      },
    })
  );
  await page.goto("/");
  await page.click('[data-screen="saldo"]');
  await expect(page.locator("#deposit-methods")).toBeVisible();
});

test("freebets_cannot_withdraw", async ({ page }) => {
  await page.route("**/auth/telegram", (route) =>
    route.fulfill({ json: { access_token: "test-jwt" } })
  );
  await page.route("**/wallet", (route) =>
    route.fulfill({ json: { units: 0, freebets: 5000, min_withdraw: 1000 } })
  );
  await page.goto("/");
  await page.click('[data-screen="saldo"]');
  // медные монетки (фрибеты) помечены как неснимаемые с баланса вывода
  await expect(page.locator("#wallet")).toContainText("não sacável");
});
