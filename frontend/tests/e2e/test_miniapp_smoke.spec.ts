import { test, expect } from "@playwright/test";
import { mockBase } from './commerce-mocks';

const CASE_JSON = {
  id: 1,
  name: "Brainrot",
  price_units: 99,
  currency: "units",
  cover: null,
  rewards: [
    { id: 11, label: "Comum barato", nominal_units: 10, weight: 1, chance_pct: 1, image: null, rarity: "common" },
    { id: 12, label: "Épico barato", nominal_units: 50, weight: 1, chance_pct: 1, image: null, rarity: "epic" },
    { id: 13, label: "Herói barato", nominal_units: 5, weight: 1, chance_pct: 1, image: null, rarity: "hero" },
    { id: 14, label: "Lenda barata", nominal_units: 1, weight: 1, chance_pct: 1, image: null, rarity: "legend" },
    { id: 15, label: "Épico caro", nominal_units: 500, weight: 1, chance_pct: 1, image: null, rarity: "epic" },
    { id: 16, label: "Normal", nominal_units: 900, weight: 1, chance_pct: 1, image: null, rarity: "normal" },
    { id: 17, label: "Comum caro", nominal_units: 1000, weight: 1, chance_pct: 1, image: null, rarity: "common" },
  ],
};

test("cases_list_and_open_case", async ({ page }) => {
  await mockBase(page);
  await page.route("**/cases", (route) => route.fulfill({ json: [CASE_JSON] }));
  await page.route("**/cases/1/open", (route) =>
    route.fulfill({
      json: {
        id: 1, item: "Épico barato", rarity: "epic", image: null,
        nominal_units: 50, chance_pct: 1, credit_units: 50,
      },
    })
  );
  await page.route("**/inventory", (route) =>
    route.fulfill({ json: [{ id: 77, label: "Épico barato", value_coins: 50, rarity: "epic", currency: "units", image: null }] })
  );
  await page.goto("/");
  await expect(page.locator(".case")).toHaveCount(1);
  await expect(page.locator(".case b")).toHaveText("Brainrot");
  await page.click(".case");
  await expect(page.locator("[data-open]")).toBeVisible();
  await expect(page.locator(".items .item b")).toHaveText([
    "Herói barato",
    "Lenda barata",
    "Épico caro",
    "Épico barato",
    "Normal",
    "Comum caro",
    "Comum barato",
  ]);
  await page.click("[data-open]");
  // рулетка ~4.5s, затем модалка выигрыша
  await expect(page.locator(".win-img")).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".win h2")).toHaveText("Épico barato");
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
    route.fulfill({ json: { session_id: 2, cups: 3, ball: 0, mult: 2.70 } })
  );
  await page.route("**/games/shell/pick", (route) =>
    route.fulfill({ json: { win: true, ball: 0, guess: 0, mult: 2.70, payout: 270 } })
  );
  await page.goto("/");
  await page.click('[data-tab="games"]');
  await page.click('[data-game="copos"]');
  await page.click("[data-tplay]");
  // шарик показан под первым стаканчиком; fullscreen flash не используется в Copos
  await expect(page.locator('.cup[data-cup="0"].up')).toBeVisible();
  await expect(page.locator('.cup.fwd, .cup.bwd')).toHaveCount(0);
  await expect(page.locator('.flash')).toHaveCount(0);
  // после перемешивания кликаем по шару (ball=0)
  await page.click('.cup[data-cup="0"]', { timeout: 15000 });
  await expect(page.locator("p.hint")).toContainText("Acertou");
  await expect(page.locator('.flash')).toHaveCount(0);
});

test("foguete_uses_server_crash_point_and_single_cashout", async ({ page }) => {
  await mockBase(page);
  await page.route("**/cases", route => route.fulfill({ json: [] }));
  let cashouts = 0;
  await page.route("**/games/crash/start", route => route.fulfill({ json: {
    session_id: 44, crash_point: 10, t0_ms: Date.now(), growth: 0.12,
  } }));
  await page.route("**/games/crash/cash*", route => {
    cashouts += 1;
    return route.fulfill({ json: { win: true, m: 2, crash: 10, payout: 200 } });
  });
  await page.goto("/");
  await page.click('[data-tab="games"]');
  await page.click('[data-game="foguete"]');
  await page.click('[data-rplay]');
  await expect(page.locator("#rmul")).toContainText("x1");
  await page.click("#rcash");
  await expect(page.locator(".rk-state")).toContainText("chegou até x10");
  expect(cashouts).toBe(1);
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
  // Безопасный default: все четыре способа показаны, но сервер их выключил.
  await expect(page.locator("#deposit-methods .dep-method")).toHaveCount(4);
  await expect(page.locator("#deposit-methods .dep-method:disabled")).toHaveCount(4);
  await expect(page.locator("#dep-amount")).toHaveValue("100");
  await expect(page.locator('[data-depquote]')).toBeDisabled();
  // Никаких фиктивных номиналов, количества или обещаний банковского вывода.
  await expect(page.locator('#withdraw h2')).toHaveText('Trocar moedas por gift card');
  await expect(page.locator("#wd-card")).toBeDisabled();
  await expect(page.locator("#wd-preview")).toContainText('Nenhuma moeda foi gasta');
  await expect(page.locator('[data-giftpreview]')).toBeDisabled();
  await expect(page.locator('#wd-count')).toHaveCount(0);
  await expect(page.locator('#create-personal-bot')).toHaveAttribute('href', 'https://t.me/windrop_bot?start=managed');
  // рефералка
  await expect(page.locator("#reflink")).toHaveValue(/WDTEST/);
});
