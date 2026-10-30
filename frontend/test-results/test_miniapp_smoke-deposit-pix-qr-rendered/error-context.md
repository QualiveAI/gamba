# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: test_miniapp_smoke.spec.ts >> deposit_pix_qr_rendered
- Location: tests\e2e\test_miniapp_smoke.spec.ts:52:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator:  locator('#deposit-methods')
Expected: visible
Received: hidden
Timeout:  5000ms

Call log:
  - Expect "toBeVisible" locator('#deposit-methods') with timeout 5000ms
  - waiting for locator('#deposit-methods')
    14 × locator resolved to <div id="deposit-methods"></div>
       - unexpected value "hidden"

```

```yaml
- banner:
  - heading "Case Platform" [level=1]
  - text: "0"
- navigation:
  - button "Cases"
  - button "Mines"
  - button "Crash"
  - button "Upgrade"
  - button "Shell"
  - button "Wallet"
  - button "Deposit"
  - button "Withdraw"
- main
```

# Test source

```ts
  1  | import { test, expect } from "@playwright/test";
  2  | 
  3  | test("deposit_and_open_case", async ({ page }) => {
  4  |   await page.route("**/auth/telegram", (route) =>
  5  |     route.fulfill({ json: { access_token: "test-jwt" } })
  6  |   );
  7  |   await page.route("**/cases", (route) =>
  8  |     route.fulfill({ json: [{ id: 1, name: "Test Case", price_units: 100 }] })
  9  |   );
  10 |   await page.route("**/deposits", (route) =>
  11 |     route.fulfill({ json: { payment_id: "p1", qr_string: "test-qr" } })
  12 |   );
  13 |   await page.route("**/cases/1/open", (route) =>
  14 |     route.fulfill({ json: { nominal_units: 50 } })
  15 |   );
  16 |   await page.goto("http://localhost:8000");
  17 |   await expect(page.locator("#cases-list")).toBeVisible();
  18 | });
  19 | 
  20 | test("withdraw_below_minimum_blocked", async ({ page }) => {
  21 |   await page.route("**/auth/telegram", (route) =>
  22 |     route.fulfill({ json: { access_token: "test-jwt" } })
  23 |   );
  24 |   await page.route("**/wallet", (route) =>
  25 |     route.fulfill({ json: { units: 500, freebets: 0, min_withdraw: 1000 } })
  26 |   );
  27 |   await page.goto("http://localhost:8000");
  28 |   await page.click('[data-screen="wallet"]');
  29 |   const btn = page.locator("#wd-btn");
  30 |   await expect(btn).toBeDisabled();
  31 |   await expect(btn).toHaveAttribute("data-disabled-reason", "below_minimum");
  32 | });
  33 | 
  34 | test("mines_reveal_and_cashout", async ({ page }) => {
  35 |   await page.route("**/auth/telegram", (route) =>
  36 |     route.fulfill({ json: { access_token: "test-jwt" } })
  37 |   );
  38 |   await page.route("**/games/mines/session", (route) =>
  39 |     route.fulfill({ json: { session_id: "s1" } })
  40 |   );
  41 |   await page.route("**/games/mines/session/s1/reveal", (route) =>
  42 |     route.fulfill({ json: { hit_mine: false, multiplier: 1.5 } })
  43 |   );
  44 |   await page.route("**/games/mines/session/s1/cashout", (route) =>
  45 |     route.fulfill({ json: { payout: 150 } })
  46 |   );
  47 |   await page.goto("http://localhost:8000");
  48 |   await page.click('[data-screen="mines"]');
  49 |   await expect(page.locator("#mines-grid")).toBeVisible();
  50 | });
  51 | 
  52 | test("deposit_pix_qr_rendered", async ({ page }) => {
  53 |   await page.route("**/auth/telegram", (route) =>
  54 |     route.fulfill({ json: { access_token: "test-jwt" } })
  55 |   );
  56 |   await page.route("**/meta/geos", (route) =>
  57 |     route.fulfill({ json: { methods: [{ name: "PIX", method: "pix" }] } })
  58 |   );
  59 |   await page.goto("http://localhost:8000");
  60 |   await page.click('[data-screen="deposit"]');
> 61 |   await expect(page.locator("#deposit-methods")).toBeVisible();
     |                                                  ^ Error: expect(locator).toBeVisible() failed
  62 | });
  63 | 
  64 | test("freebets_cannot_withdraw", async ({ page }) => {
  65 |   await page.route("**/auth/telegram", (route) =>
  66 |     route.fulfill({ json: { access_token: "test-jwt" } })
  67 |   );
  68 |   await page.route("**/wallet", (route) =>
  69 |     route.fulfill({ json: { units: 0, freebets: 5000, min_withdraw: 1000 } })
  70 |   );
  71 |   await page.goto("http://localhost:8000");
  72 |   await page.click('[data-screen="wallet"]');
  73 |   const btn = page.locator("#wd-freebets-btn");
  74 |   await expect(btn).toBeDisabled();
  75 | });
```