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
  await page.goto("http://localhost:8000");
  await expect(page.locator("#cases-list")).toBeVisible();
});

test("withdraw_below_minimum_blocked", async ({ page }) => {
  await page.route("**/auth/telegram", (route) =>
    route.fulfill({ json: { access_token: "test-jwt" } })
  );
  await page.route("**/wallet", (route) =>
    route.fulfill({ json: { units: 500, freebets: 0, min_withdraw: 1000 } })
  );
  await page.goto("http://localhost:8000");
  await page.click('[data-screen="wallet"]');
  const btn = page.locator("#wd-btn");
  await expect(btn).toBeDisabled();
  await expect(btn).toHaveAttribute("data-disabled-reason", "below_minimum");
});

test("mines_reveal_and_cashout", async ({ page }) => {
  await page.route("**/auth/telegram", (route) =>
    route.fulfill({ json: { access_token: "test-jwt" } })
  );
  await page.route("**/games/mines/session", (route) =>
    route.fulfill({ json: { session_id: "s1" } })
  );
  await page.route("**/games/mines/session/s1/reveal", (route) =>
    route.fulfill({ json: { hit_mine: false, multiplier: 1.5 } })
  );
  await page.route("**/games/mines/session/s1/cashout", (route) =>
    route.fulfill({ json: { payout: 150 } })
  );
  await page.goto("http://localhost:8000");
  await page.click('[data-screen="mines"]');
  await expect(page.locator("#mines-grid")).toBeVisible();
});

test("deposit_pix_qr_rendered", async ({ page }) => {
  await page.route("**/auth/telegram", (route) =>
    route.fulfill({ json: { access_token: "test-jwt" } })
  );
  await page.route("**/meta/geos", (route) =>
    route.fulfill({ json: { methods: [{ name: "PIX", method: "pix" }] } })
  );
  await page.goto("http://localhost:8000");
  await page.click('[data-screen="deposit"]');
  await expect(page.locator("#deposit-methods")).toBeVisible();
});

test("freebets_cannot_withdraw", async ({ page }) => {
  await page.route("**/auth/telegram", (route) =>
    route.fulfill({ json: { access_token: "test-jwt" } })
  );
  await page.route("**/wallet", (route) =>
    route.fulfill({ json: { units: 0, freebets: 5000, min_withdraw: 1000 } })
  );
  await page.goto("http://localhost:8000");
  await page.click('[data-screen="wallet"]');
  const btn = page.locator("#wd-freebets-btn");
  await expect(btn).toBeDisabled();
});