import { test, expect } from '@playwright/test';

async function waitForPick(page: import('@playwright/test').Page) {
  await expect(page.locator('.cup').first()).toBeEnabled({ timeout: 20000 });
}

async function playRound(page: import('@playwright/test').Page, cup: number, expectedCups: number) {
  await page.getByRole('button', { name: /Jogar|Continuar|De novo/ }).click();
  await expect(page.locator('.cup')).toHaveCount(expectedCups, { timeout: 3000 });
  await expect(page.locator('.cup').first()).toBeDisabled();
  await waitForPick(page);
  await page.locator(`.cup[data-cup="${cup}"]`).click();
  return await page.locator('p.hint').first().innerText();
}

async function decodeImages(page: import('@playwright/test').Page) {
  return page.evaluate(async () => {
    const urls = [...new Set([...document.images].map(image => image.currentSrc || image.src))];
    return Promise.all(urls.map(src => new Promise(resolve => {
      const image = new Image();
      image.onload = () => resolve({ src, width: image.naturalWidth, ok: true });
      image.onerror = () => resolve({ src, width: 0, ok: false });
      image.src = src;
    })));
  });
}

test('local preview opens with simulated auth, canonical assets and local gameplay', async ({ page }) => {
  const external: string[] = [];
  const failedImages: string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) external.push(url.href);
  });
  page.on('requestfailed', request => {
    if (request.resourceType() === 'image') failedImages.push(request.url());
  });

  await page.goto('/preview.html');
  await expect(page.locator('.local-preview-banner')).toContainText('TELEGRAM AUTH SIMULATED');
  await expect(page.getByRole('heading', { name: 'Caixas', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ouro', exact: true })).toHaveText('5.000');
  await expect(page.getByRole('button', { name: 'Cobre', exact: true })).toHaveText('1.200');
  await expect(page.locator('.case')).toHaveCount(10);

  const imageState = await page.locator('img').evaluateAll(images => images.map(image => ({
    src: image.currentSrc || image.src, complete: image.complete, width: image.naturalWidth,
  })));
  expect(imageState.length).toBeGreaterThan(10);
  const decoded = await decodeImages(page);
  expect(decoded.length).toBeGreaterThan(10);
  expect(decoded.every(image => image.ok && image.width > 0 && new URL(image.src).pathname.endsWith('.webp'))).toBe(true);
  await expect(page.locator('img.broken')).toHaveCount(0);
  expect(failedImages).toEqual([]);

  await page.getByRole('button', { name: 'Jogos', exact: true }).click();
  await page.locator('[data-game="copos"]').click();
  await expect(page.getByRole('heading', { name: 'Copos', exact: true })).toBeVisible();
  const firstHint = await playRound(page, 0, 3);
  expect(firstHint).toContain('Acertou');
  await expect(page.locator('.cup')).toHaveCount(3);
  await expect(page.locator('.flash, .cup.fwd, .cup.bwd')).toHaveCount(0);
  await expect(page.locator('#modal')).toBeHidden();

  const secondHint = await playRound(page, 1, 3);
  expect(secondHint).toContain('Acertou');
  await expect(page.locator('.cup')).toHaveCount(3);
  await expect(page.locator('.flash, .cup.fwd, .cup.bwd')).toHaveCount(0);
  await expect(page.locator('#modal')).toBeHidden();

  const thirdHint = await playRound(page, 2, 4);
  expect(thirdHint).toContain('Acertou');
  await expect(page.locator('.cup')).toHaveCount(4);
  await expect(page.locator('.flash, .cup.fwd, .cup.bwd')).toHaveCount(0);

  await page.getByRole('button', { name: 'Caixas', exact: true }).click();
  await expect(page.locator('#modal')).toBeHidden();
  await expect(page.getByRole('heading', { name: 'Caixas', exact: true })).toBeVisible();
  await expect(page.locator('html')).toHaveJSProperty('scrollWidth', 1280);
  expect(external).toEqual([]);
});

test('local preview can display a real Copos loss without credit', async ({ page }) => {
  await page.goto('/preview.html');
  await page.getByRole('button', { name: 'Jogos', exact: true }).click();
  await page.locator('[data-game="copos"]').click();
  await expect(page.getByRole('button', { name: /Jogar/ })).toBeVisible();
  await page.getByRole('button', { name: /Jogar/ }).click();
  await waitForPick(page);
  await page.locator('.cup[data-cup="1"]').click();
  await expect(page.locator('p.hint').first()).toContainText('Errou');
  await expect(page.getByRole('button', { name: 'Ouro', exact: true })).toHaveText('4.950');
  await expect(page.locator('.flash, .cup.fwd, .cup.bwd')).toHaveCount(0);
});

test('Aprimorar resolves duplicate-rid target and keeps wallet unchanged', async ({ page }) => {
  await page.goto('/preview.html');
  await page.getByRole('button', { name: 'Aprimorar', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Aprimorar', exact: true })).toBeVisible();
  await page.locator('[data-upsel]').first().click();
  const target = page.locator('[data-uptgt="2:1"]');
  await expect(target).toBeVisible();
  await expect(target).toContainText('40');
  await target.click();
  await expect(page.locator('[data-upgo]')).toBeEnabled();
  await page.locator('[data-upgo]').click();
  await expect(page.locator('#modal')).toBeVisible({ timeout: 8000 });
  await expect(page.locator('#modal')).toContainText('Deu certo');
  await expect(page.getByRole('button', { name: 'Ouro', exact: true })).toHaveText('5.000');
  await page.getByRole('button', { name: 'Beleza', exact: true }).click();
  await expect(page.locator('#modal')).toBeHidden();
  await page.getByRole('button', { name: 'Mochila', exact: true }).click();
  await expect(page.locator('.item')).toContainText('Patinete básico');
});

test('Foguete supports manual cashout in local preview', async ({ page }) => {
  await page.goto('/preview.html');
  await page.getByRole('button', { name: 'Jogos', exact: true }).click();
  await page.locator('[data-game="foguete"]').click();
  await page.getByRole('button', { name: /Lançar/ }).click();
  await expect(page.locator('#rmul')).toContainText('x1');
  await expect(page.locator('#rcash')).toBeVisible();
  await page.locator('#rcash').click();
  await expect(page.locator('.rk-state')).toContainText('chegou até');
  const history = await page.locator('.rk-hist span').first().innerText();
  const crashValue = Number(history.replace('x', ''));
  expect(crashValue).toBeGreaterThanOrEqual(1.2);
  expect(crashValue).toBeLessThanOrEqual(6);
  const gold = await page.getByRole('button', { name: 'Ouro', exact: true }).innerText();
  expect(Number(gold.replace(/\D/g, ''))).toBeGreaterThanOrEqual(4950);
});

test('Foguete crash points vary between rounds', async ({ page }) => {
  await page.goto('/preview.html');
  await page.getByRole('button', { name: 'Jogos', exact: true }).click();
  await page.locator('[data-game="foguete"]').click();
  const points: number[] = [];
  for (let round = 0; round < 3; round++) {
    await page.getByRole('button', { name: /Lançar/ }).click();
    await expect(page.locator('#rcash')).toBeVisible();
    await page.locator('#rcash').click();
    await expect(page.locator('.rk-state')).toContainText('chegou até');
    points.push(Number((await page.locator('.rk-hist span').first().innerText()).replace('x', '')));
  }
  expect(new Set(points).size).toBeGreaterThan(1);
});

test('Foguete can end in a server-shaped crash without payout', async ({ page }) => {
  await page.goto('/preview.html');
  await page.getByRole('button', { name: 'Jogos', exact: true }).click();
  await page.locator('[data-game="foguete"]').click();
  let crashed = false;
  for (let attempt = 0; attempt < 8 && !crashed; attempt++) {
    await page.getByRole('button', { name: /Lançar|De novo/ }).click();
    try {
      await expect(page.locator('.rk-state')).toContainText('Rodada encerrada', { timeout: 25000 });
      crashed = true;
    } catch {
      await expect(page.locator('.rk-state')).toContainText('chegou até');
    }
  }
  expect(crashed).toBe(true);
  const gold = await page.getByRole('button', { name: 'Ouro', exact: true }).innerText();
  expect(Number(gold.replace(/\D/g, ''))).toBeLessThan(5000);
});

test('ordinary entrypoint still requires Telegram', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Abrir pelo Telegram', exact: true })).toBeVisible();
});
