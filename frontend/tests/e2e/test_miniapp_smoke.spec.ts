import { test, expect } from "@playwright/test";

// Базовые моки для всех тестов: auth, баланс, бренд, гео
async function mockBase(page) {
  await page.route("**/auth/telegram", (route) =>
    route.fulfill({ json: { access_token: "test-jwt" } })
  );
  await page.route("**/wallet", (route) =>
    route.fulfill({ json: { units_minor: 1000, freebets_units: 500 } })
  );
  await page.route("**/meta/tenant", (route) =>
    route.fulfill({
      json: { tenant: "default", brand: { name: "ROBLOXWINDROP", logo_url: "", primary_color: "#c8102e" }, domains: {}, geos: ["BR"], games: ["roblox"] },
    })
  );
  await page.route("**/meta/geos", (route) =>
    route.fulfill({ json: [{ geo: "BR", methods: ["card", "crypto"] }] })
  );
}

const CASE_JSON = {
  id: 1,
  name: "Brainrot",
  price_units: 99,
  currency: "units",
  cover: null,
  rewards: [
    { id: 11, label: "10 Robux", nominal_units: 10, weight: 16, chance_pct: 16, image: null, rarity: "common" },
    { id: 12, label: "Pet Gigachad Doge", nominal_units: 500, weight: 1.5, chance_pct: 1.5, image: null, rarity: "epic" },
    { id: 13, label: "JACKPOT 5.000 Robux", nominal_units: 5000, weight: 0.001, chance_pct: 0.001, image: null, rarity: "hero" },
  ],
};

test("cases_list_and_open_case", async ({ page }) => {
  await mockBase(page);
  await page.route("**/cases", (route) => route.fulfill({ json: [CASE_JSON] }));
  await page.route("**/cases/1/open", (route) =>
    route.fulfill({
      json: {
        id: 1, item: "Pet Gigachad Doge", rarity: "epic", image: null,
        nominal_units: 500, chance_pct: 1.5, credit_units: 500,
      },
    })
  );
  await page.route("**/inventory", (route) =>
    route.fulfill({ json: [{ id: 77, label: "Pet Gigachad Doge", value_coins: 500, rarity: "epic", currency: "units", image: null }] })
  );
  await page.goto("/");
  await expect(page.locator(".case")).toHaveCount(1);
  await expect(page.locator(".case b")).toHaveText("Brainrot");
  await page.click(".case");
  await expect(page.locator("[data-open]")).toBeVisible();
  await page.click("[data-open]");
  // рулетка ~4.5s, затем модалка выигрыша
  await expect(page.locator(".win-img")).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".win h2")).toHaveText("Pet Gigachad Doge");
  await page.click("[data-close]");
  // после закрытия остаёмся на странице кейса
  await expect(page.locator("[data-open]")).toBeVisible();
});

test("inventory_sell_item", async ({ page }) => {
  await mockBase(page);
  await page.route("**/cases", (route) => route.fulfill({ json: [] }));
  await page.route("**/inventory", (route) =>
    route.fulfill({ json: [{ id: 77, label: "Pet Teste", value_coins: 120, rarity: "epic", currency: "units", image: null }] })
  );
  await page.route("**/inventory/77/sell", (route) =>
    route.fulfill({ json: { sold: true, value: 120, currency: "units" } })
  );
  await page.goto("/");
  await page.click('[data-tab="inventory"]');
  await expect(page.locator(".inv-head")).toContainText("120");
  await page.click('[data-sell="77"]');
  // чип золота анимируется к 1000 + 120
  await expect(page.locator("#bg")).toContainText("1.120", { timeout: 5000 });
});

test("mines_reveal_and_cashout", async ({ page }) => {
  await mockBase(page);
  await page.route("**/cases", (route) => route.fulfill({ json: [] }));
  await page.route("**/games/mines/start", (route) =>
    route.fulfill({ json: { session_id: 1, grid_size: 25, mine_count: 3 } })
  );
  await page.route("**/games/mines/reveal", (route) =>
    route.fulfill({ json: { hit_mine: false, revealed: [0], bias_applied: false } })
  );
  await page.route("**/games/mines/cashout*", (route) =>
    route.fulfill({ json: { payout: 110, revealed: 1 } })
  );
  await page.goto("/");
  await page.click('[data-tab="games"]');
  await page.click('[data-game="minas"]');
  await page.click("[data-mplay]");
  await expect(page.locator(".mines-grid")).toBeVisible();
  await page.click('[data-cell="0"]');
  await expect(page.locator('[data-cell="0"].gem')).toBeVisible();
  await page.click("[data-mcash]");
  await expect(page.locator(".mines-grid ~ .hint, p.hint")).toContainText("Sacou");
});

test("copos_levels_flow", async ({ page }) => {
  await mockBase(page);
  await page.route("**/cases", (route) => route.fulfill({ json: [] }));
  await page.route("**/games/shell/start", (route) =>
    route.fulfill({ json: { session_id: 2, cups: 3, ball: 0, mult: 2.91 } })
  );
  await page.route("**/games/shell/pick", (route) =>
    route.fulfill({ json: { win: true, ball: 0, guess: 0, mult: 2.91, payout: 291 } })
  );
  await page.goto("/");
  await page.click('[data-tab="games"]');
  await page.click('[data-game="copos"]');
  await page.click("[data-tplay]");
  // шарик показан под первым стаканчиком
  await expect(page.locator('.cup[data-cup="0"].up')).toBeVisible();
  // после перемешивания кликаем по шару (ball=0)
  await page.click('.cup[data-cup="0"]', { timeout: 15000 });
  await expect(page.locator("p.hint")).toContainText("Acertou");
});

test("profile_daily_deposit_withdraw", async ({ page }) => {
  await mockBase(page);
  await page.route("**/cases", (route) => route.fulfill({ json: [] }));
  await page.route("**/rewards/daily/status", (route) =>
    route.fulfill({ json: { can_claim: true, streak: 3, claimed_dates: [new Date().toISOString().slice(0, 10)] } })
  );
  await page.route("**/rewards/daily/claim", (route) =>
    route.fulfill({ json: { amount: 500, streak: 4 } })
  );
  await page.route("**/referrals/my", (route) =>
    route.fulfill({ json: { link: "https://t.me/windrop_bot?start=WDTEST", invited: 2, confirmed: 1 } })
  );
  await page.route("**/wallet/history", (route) => route.fulfill({ json: [] }));
  await page.goto("/");
  await page.click('[data-tab="profile"]');
  // check-in
  await expect(page.locator("[data-claim]")).toBeEnabled();
  // депозит: методы + сумма
  await expect(page.locator("#deposit-methods .dep-method")).toHaveCount(2);
  await expect(page.locator("#dep-amount")).toHaveValue("100");
  // вывод: селект карт и предпросмотр
  await expect(page.locator("#wd-card")).toBeVisible();
  await expect(page.locator("#wd-preview")).toContainText("$15.00");
  // рефералка
  await expect(page.locator("#reflink")).toHaveValue(/WDTEST/);
});
