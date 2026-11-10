// Скриншоты экранов мини-аппа (QA): node shots.mjs из frontend/
// Живой стек на 8090, QA-токен из Temp. Результат в ../shots/*.png
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

mkdirSync("../shots", { recursive: true });

// Гостевой вход теперь автоматический: пустой initData -> dev-гость на бэкенде
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 390, height: 844 } });
await page.goto("http://localhost:8090/app/");
await page.waitForTimeout(1800);

const shot = async (n, full = false) => {
  await page.screenshot({ path: `../shots/${n}.png`, fullPage: full });
  console.log("shot", n);
};

await shot("01-caixas");
// карточка кейса
await page.locator(".case").first().click();
await page.waitForTimeout(700);
await shot("02-case");
// открытие кейса (реальный API, QA-баланс)
await page.locator("[data-open]").click();
await page.waitForTimeout(5300);
await shot("03-roulette-win");
// назад, игры
await page.locator(".x[data-close]").click();
await page.waitForTimeout(300);
await page.locator('[data-tab="games"]').click();
await page.waitForTimeout(400);
await shot("04-jogos");
// mines
await page.locator('[data-game="minas"]').click();
await page.waitForTimeout(300);
await shot("05-minas");
// copos
await page.locator(".back").click();
await page.locator('[data-game="copos"]').click();
await page.waitForTimeout(300);
await shot("06-copos");
// foguete
await page.locator(".back").click();
await page.locator('[data-game="foguete"]').click();
await page.waitForTimeout(300);
await shot("07-foguete");
// aprimorar (после открытия кейса в инвентаре есть предмет)
await page.locator('[data-tab="upgrade"]').click();
await page.waitForTimeout(400);
await shot("08-aprimorar");
// mochila
await page.locator('[data-tab="inventory"]').click();
await page.waitForTimeout(400);
await shot("09-mochila");
// perfil (полная страница)
await page.locator('.nav [data-tab="profile"]').click();
await page.waitForTimeout(800);
await shot("10-perfil", true);

await b.close();
console.log("done");
