import { test, expect } from '@playwright/test';
import { mockBase, methodMeta, paymentQuote, paymentIntent, redemption, SKU, IID, QID, SDK_SCRIPT } from './commerce-mocks';

test('initial_wallet_does_not_wait_for_animation_frames', async ({ page }) => {
  await mockBase(page);
  await page.addInitScript(() => { window.requestAnimationFrame = () => 1; });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Caixas', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ouro', exact: true })).toHaveText('1.000');
  await expect(page.getByRole('button', { name: 'Cobre', exact: true })).toHaveText('500');
});

test('quote_confirm_timeout_retry_uses_same_key_and_sandbox_does_not_credit_real_balance', async ({ page }) => {
  const base = await mockBase(page);
  const quoteBodies: unknown[] = [], posts: Record<string, unknown>[] = [];
  let settles = 0, polls = 0, settled = false;
  await page.route('**/meta/payment-methods', route => route.fulfill({ json: methodMeta('sandbox') }));
  await page.route('**/deposits/quote', route => {
    quoteBodies.push(route.request().postDataJSON());
    return route.fulfill({ json: paymentQuote() });
  });
  await page.route('**/deposits', route => {
    posts.push(route.request().postDataJSON());
    if (posts.length === 1) return route.abort('timedout');
    return route.fulfill({ json: paymentIntent() });
  });
  await page.route(`**/deposits/${IID}`, route => {
    polls++;
    return route.fulfill({ json: paymentIntent({ status: settled ? 'sandbox_succeeded' : 'pending', quote: paymentQuote() }) });
  });
  await page.route(`**/deposits/${IID}/sandbox-settle`, route => {
    settles++; settled = true;
    return route.fulfill({ json: { status: 'sandbox_succeeded', credited: false, intent_id: IID } });
  });
  await page.goto('/#deposit');
  await expect(page.locator('[data-depmethod="card"]')).toBeEnabled();
  await page.click('[data-depmethod="card"]'); await page.click('[data-depquote]');
  await expect(page.locator('#dep-preview')).toContainText('12,34');
  await expect(page.locator('#dep-preview')).toContainText('0,66');
  await expect(page.locator('#dep-preview')).toContainText('13,00');
  expect(posts).toHaveLength(0);
  expect(quoteBodies).toEqual([{ coins: 100, method: 'card', channel: 'telegram' }]);
  await page.click('[data-depconfirm]');
  await expect(page.locator('[data-depconfirm]')).toHaveText('Repetir confirmação com segurança');
  await expect(page.locator('#dep-amount')).toBeDisabled();
  expect(posts).toHaveLength(1);
  // Reload восстанавливает ту же попытку; POST не выполняется автоматически.
  await page.reload();
  await expect(page.locator('[data-depconfirm]')).toHaveText('Repetir confirmação com segurança');
  expect(posts).toHaveLength(1);
  await page.click('[data-depconfirm]');
  await expect(page.locator('#dep-status')).toContainText(IID);
  expect(posts).toHaveLength(2); expect(posts[0]).toEqual(posts[1]);
  expect(Object.keys(posts[0]).sort()).toEqual(['idempotency_key', 'quote_id']);
  expect(posts[0].quote_id).toBe(QID);
  expect(settles).toBe(0);
  const stored = await page.evaluate(() => Object.values(sessionStorage).join(''));
  expect(stored).not.toContain(String(posts[0].idempotency_key));
  expect(stored).not.toContain('signed-test-init-data'); expect(stored).not.toContain('invoice_link');
  await page.click('[data-depsandbox]');
  await expect(page.locator('#dep-status')).toContainText('Solicitação concluída pelo servidor.');
  expect(settles).toBe(1); expect(polls).toBeGreaterThan(0);
  await expect(page.locator('#bg')).toContainText('1.000');
  await expect(page.locator('#profile-gold')).toHaveText('1.000');
  expect(base.unexpected).toEqual([]);
});

test('amount_method_and_expiration_invalidate_the_quote', async ({ page }) => {
  await mockBase(page);
  let quotes = 0, deposits = 0;
  await page.route('**/meta/payment-methods', route => route.fulfill({ json: methodMeta('sandbox') }));
  await page.route('**/deposits/quote', route => {
    quotes++;
    return route.fulfill({ json: paymentQuote({ expires_at: new Date(Date.now() + (quotes === 3 ? 1200 : 60000)).toISOString() }) });
  });
  await page.route('**/deposits', route => { deposits++; return route.fulfill({ json: paymentIntent() }); });
  await page.goto('/#deposit'); await page.click('[data-depmethod="card"]');
  await page.click('[data-depquote]'); await expect(page.locator('[data-depconfirm]')).toBeVisible();
  await page.fill('#dep-amount', '500'); await expect(page.locator('[data-depconfirm]')).toHaveCount(0);
  await page.fill('#dep-amount', '100'); await page.click('[data-depquote]');
  await expect(page.locator('[data-depconfirm]')).toBeVisible();
  await page.click('[data-depmethod="stars"]'); await expect(page.locator('[data-depconfirm]')).toHaveCount(0);
  await page.click('[data-depmethod="card"]'); await page.click('[data-depquote]');
  await expect(page.locator('#deposit')).toContainText('A cotação expirou', { timeout: 5000 });
  await expect(page.locator('[data-depconfirm]')).toHaveCount(0);
  expect(deposits).toBe(0);
});

test('disabled_and_missing_new_api_never_fall_back_to_legacy_payments', async ({ page }) => {
  const base = await mockBase(page);
  await page.route('**/meta/payment-methods', route => route.fulfill({ status: 404, json: { detail: 'Not Found SECRET' } }));
  await page.route('**/giftcards/catalog', route => route.fulfill({ status: 503, json: { detail: '<img src=x onerror=alert(1)>SECRET' } }));
  await page.goto('/#deposit');
  await expect(page.locator('#deposit-methods .dep-method')).toHaveCount(4);
  await expect(page.locator('#deposit-methods .dep-method:disabled')).toHaveCount(4);
  await expect(page.locator('#deposit')).toContainText('Serviço indisponível');
  await expect(page.locator('[data-depquote]')).toBeDisabled();
  await expect(page.locator('[data-giftpreview]')).toBeDisabled();
  await expect(page.locator('body')).not.toContainText('SECRET');
  await expect(page.locator('#deposit img, #withdraw img')).toHaveCount(0);
  expect(base.unexpected).toEqual([]);
});

test('gift_empty_catalog_cannot_spend_coins', async ({ page }) => {
  await mockBase(page); let posts = 0;
  await page.route('**/giftcards/catalog', route => route.fulfill({ json: { enabled: true, mode: 'live', items: [] } }));
  await page.route('**/redemptions', route => {
    if (route.request().method() === 'POST') posts++;
    return route.fulfill({ json: [] });
  });
  await page.goto('/#withdraw');
  await expect(page.locator('#withdraw h2')).toHaveText('Trocar moedas por gift card');
  await expect(page.locator('#wd-card')).toBeDisabled();
  await expect(page.locator('[data-giftpreview]')).toBeDisabled();
  await expect(page.locator('#withdraw')).toContainText('Nenhuma moeda será gasta');
  await expect(page.locator('#wd-count')).toHaveCount(0);
  await expect(page.locator('#bg')).toContainText('1.000'); expect(posts).toBe(0);
});

test('gift_stocked_sku_explicit_confirm_then_server_balance_and_bot_delivery_status', async ({ page }) => {
  const base = await mockBase(page);
  let accepted = false, delivered = false; const bodies: Record<string, unknown>[] = [];
  await page.route('**/giftcards/catalog', route => route.fulfill({ json: { enabled: true, mode: 'live', items: [SKU] } }));
  await page.route('**/wallet', route => route.fulfill({ json: { units_minor: accepted ? 100 : 1000, freebets_units: 500 } }));
  await page.route('**/redemptions', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: accepted ? [redemption()] : [] });
    bodies.push(route.request().postDataJSON());
    await new Promise(resolve => setTimeout(resolve, 1200));
    accepted = true;
    return route.fulfill({ json: redemption({ code: 'SECRET-CODE-NEVER-DISPLAY' }) });
  });
  await page.route('**/redemptions/51', route => route.fulfill({ json: redemption({ status: delivered ? 'issued' : 'pending', code: 'SECRET-CODE-NEVER-DISPLAY' }) }));
  await page.goto('/#withdraw');
  await expect(page.locator('#wd-preview')).toContainText('50,00');
  await expect(page.locator('#wd-preview')).toContainText('900 moedas');
  await page.click('[data-giftpreview]');
  await expect(page.locator('#gift-confirmation')).toContainText('1 Roblox');
  expect(bodies).toHaveLength(0);
  await page.click('[data-giftconfirm]');
  await expect(page.locator('#bg')).toContainText('1.000');
  await expect(page.locator('#wd-status')).toContainText('Pedido recebido');
  expect(bodies).toHaveLength(1); expect(bodies[0].sku_id).toBe(SKU.id);
  expect(Object.keys(bodies[0]).sort()).toEqual(['idempotency_key', 'sku_id']);
  await expect(page.locator('#bg')).toHaveText('100');
  await expect(page.locator('#profile-gold')).toHaveText('100');
  await expect(page.locator('body')).not.toContainText('SECRET-CODE');
  expect(await page.evaluate(() => Object.values(sessionStorage).join(''))).not.toContain('SECRET-CODE');
  delivered = true; await page.click('[data-giftcheck]');
  await expect(page.locator('#wd-status')).toContainText('Gift card enviado pelo bot no Telegram');
  expect(base.unexpected).toEqual([]);
});

test('payment_poll_and_late_profile_refresh_do_not_replace_an_active_game', async ({ page }) => {
  await mockBase(page); let profileStatusCalls = 0, paid = false;
  await page.route('**/rewards/daily/status', async route => {
    profileStatusCalls++;
    if (profileStatusCalls > 1) await new Promise(resolve => setTimeout(resolve, 1800));
    return route.fulfill({ json: { can_claim: true, streak: 3, claimed_dates: [] } });
  });
  await page.route('**/meta/payment-methods', route => route.fulfill({ json: methodMeta('live') }));
  await page.route('**/deposits/quote', route => route.fulfill({ json: paymentQuote({ mode: 'live' }) }));
  await page.route('**/deposits', route => route.fulfill({ json: paymentIntent({ mode: 'live', client_payload: { action: 'pending_review' } }) }));
  await page.route(`**/deposits/${IID}`, route => { paid = true; return route.fulfill({ json: paymentIntent({ mode: 'live', status: 'succeeded', client_payload: {} }) }); });
  await page.route('**/wallet', route => route.fulfill({ json: { units_minor: paid ? 1100 : 1000, freebets_units: 500 } }));
  await page.route('**/games/mines/start', route => route.fulfill({ json: { session_id: 1, grid_size: 25, mine_count: 3 } }));
  await page.goto('/#deposit'); await page.click('[data-depmethod="card"]');
  await page.click('[data-depquote]'); await page.click('[data-depconfirm]');
  await expect(page.locator('#dep-status')).toBeVisible();
  await page.click('.nav [data-tab="games"]'); await page.click('[data-game="minas"]'); await page.click('[data-mplay]');
  await expect(page.locator('[data-cell="0"]')).toBeEnabled();
  // Метка реального DOM-узла исчезла бы при глобальном render().
  await page.locator('.mines-grid').evaluate(node => node.setAttribute('data-retained', 'active-round'));
  await expect(page.locator('#bg')).toContainText('1.100', { timeout: 8000 });
  await expect(page.locator('.mines-grid')).toHaveAttribute('data-retained', 'active-round');
  await expect(page.locator('#view > h1')).toHaveText('Minas');
  await expect(page.locator('#deposit')).toHaveCount(0);
});

test('stars_invoice_is_opened_only_by_explicit_sdk_tap_not_by_quote_or_server_response', async ({ page }) => {
  await mockBase(page);
  await page.route('**/meta/payment-methods', route => route.fulfill({ json: methodMeta('live') }));
  await page.route('**/deposits/quote', route => route.fulfill({ json: paymentQuote({ mode: 'live', method: 'stars', rail: 'stars', provider_amount_atomic: '300', provider_currency: 'XTR', provider_exponent: 0 }) }));
  const data = paymentIntent({ mode: 'live', method: 'stars', rail: 'stars', client_payload: { action: 'invoice_required' } });
  await page.route('**/deposits', route => route.fulfill({ json: data }));
  await page.route(`**/deposits/${IID}`, route => route.fulfill({ json: data }));
  await page.route('**/payments/stars/invoice', route => route.fulfill({ json: { invoice_link: 'https://t.me/$test_invoice', mode: 'live' } }));
  await page.goto('/#deposit'); await page.click('[data-depquote]');
  await expect(page.locator('#dep-preview')).toContainText('300 XTR');
  await page.click('[data-depconfirm]'); await page.click('[data-depinvoice]');
  await expect(page.locator('[data-depopeninvoice]')).toBeVisible();
  expect(await page.evaluate(() => (window as any).__invoiceCalls)).toEqual([]);
  await page.click('[data-depopeninvoice]');
  expect(await page.evaluate(() => (window as any).__invoiceCalls)).toEqual(['https://t.me/$test_invoice']);
  await expect(page.locator('#dep-status')).toContainText('Aguardando confirmação');
  await expect(page.locator('#bg')).toContainText('1.000');
});

test('unknown_payment_link_is_not_rendered_as_navigation', async ({ page }) => {
  await mockBase(page);
  await page.route('**/meta/payment-methods', route => route.fulfill({ json: methodMeta('live') }));
  await page.route('**/deposits/quote', route => route.fulfill({ json: paymentQuote({ mode: 'live' }) }));
  await page.route('**/deposits', route => route.fulfill({ json: paymentIntent({ mode: 'live', client_payload: { action: 'pending_review', payment_url: 'javascript:alert(document.cookie)' } }) }));
  await page.goto('/#deposit'); await page.click('[data-depmethod="card"]');
  await page.click('[data-depquote]'); await page.click('[data-depconfirm]');
  await expect(page.locator('#deposit')).toContainText('O link de pagamento não foi validado');
  await expect(page.locator('#deposit a[href^="javascript:"]')).toHaveCount(0);
});

test('managed_auth_context_and_deep_links_do_not_accept_client_owner_fields', async ({ page }) => {
  const base = await mockBase(page, { bot: 777777, scope: 'managed', sdk: SDK_SCRIPT.replace("start_param: ''", "start_param: 'withdraw'") });
  await page.route('**/bots/me', route => route.fulfill({ json: { enabled: true, main_bot_username: 'windrop_bot',
    managed_bots: [{ bot_id: 777777, username: 'personal_bot', status: 'active' }], create_url: 'https://t.me/windrop_bot?start=managed' } }));
  await page.goto('/?auth_bot_id=777777&owner_telegram_id=888888');
  await expect(page.locator('#withdraw')).toBeVisible();
  await expect(page.locator('#personal-bot')).toContainText('@personal_bot');
  await expect(page.locator('#create-personal-bot')).toHaveAttribute('href', 'https://t.me/windrop_bot?start=managed');
  expect(base.authBodies).toEqual([{ init_data: 'signed-test-init-data', auth_bot_id: 777777 }]);
  await page.click('.nav [data-tab="games"]');
  await page.evaluate(() => { window.location.hash = 'deposit'; });
  await expect(page.locator('#deposit')).toBeVisible();
  await expect(page.locator('.nav [data-tab="profile"]')).toHaveClass('on');
  expect(base.authBodies).toHaveLength(1);
});

test('empty_sdk_displays_telegram_entry_without_auth_or_fake_empty_catalog', async ({ page }) => {
  const base = await mockBase(page, { sdk: SDK_SCRIPT.replace("initData: 'signed-test-init-data'", "initData: ''") });
  await page.goto('/#deposit');
  await expect(page.locator('#view h1')).toHaveText('Abrir pelo Telegram');
  await expect(page.locator('#view')).toContainText('/start');
  await expect(page.locator('#view')).not.toContainText('Nenhuma caixa ainda');
  expect(base.authBodies).toHaveLength(0);
});

test('referral_api_unavailable_disables_copy_and_share_without_a_fake_link', async ({ page }) => {
  const base = await mockBase(page);
  await page.route('**/referrals/my', route => route.fulfill({ status: 503, json: { detail: 'referral_service_unavailable' } }));
  await page.goto('/#deposit');
  await expect(page.locator('#profile-referrals [data-copy]')).toBeDisabled();
  await expect(page.locator('#profile-referrals [data-share]')).toBeDisabled();
  await expect(page.locator('#reflink')).toHaveValue('');
  await expect(page.locator('#profile-referrals')).toContainText('Link de convite indisponível');
  expect(base.unexpected).toEqual([]);
});

test('referral_invalid_server_link_is_not_available_for_copy_or_share', async ({ page }) => {
  await mockBase(page);
  await page.route('**/referrals/my', route => route.fulfill({ json: {
    link: 'https://t.me.evil.invalid/configured_bot?start=ref_41', invited: 2, confirmed: 1,
  } }));
  await page.goto('/#deposit');
  await expect(page.locator('#profile-referrals [data-copy]')).toBeDisabled();
  await expect(page.locator('#profile-referrals [data-share]')).toBeDisabled();
  await expect(page.locator('#reflink')).toHaveValue('');
  await expect(page.locator('#profile-referrals')).toContainText('Link de convite indisponível');
});

test('referral_refresh_failure_clears_previously_available_link', async ({ page }) => {
  await mockBase(page);
  let unavailable = false, requests = 0;
  await page.route('**/referrals/my', route => {
    requests++;
    return unavailable
      ? route.fulfill({ status: 503, json: { detail: 'referral_service_unavailable' } })
      : route.fulfill({ json: { link: 'https://t.me/configured_bot?start=ref_41', invited: 2, confirmed: 1 } });
  });
  await page.route('**/rewards/daily/claim', route => route.fulfill({ json: { amount: 500, streak: 1 } }));
  await page.goto('/#deposit');
  await expect(page.locator('#reflink')).toHaveValue('https://t.me/configured_bot?start=ref_41');
  await expect(page.locator('#profile-referrals [data-copy]')).toBeEnabled();
  await expect(page.locator('#profile-referrals [data-share]')).toBeEnabled();
  await expect.poll(() => requests).toBeGreaterThanOrEqual(2);
  unavailable = true;
  await page.click('[data-claim]');
  await expect(page.locator('#reflink')).toHaveValue('');
  await expect(page.locator('#profile-referrals [data-copy]')).toBeDisabled();
  await expect(page.locator('#profile-referrals [data-share]')).toBeDisabled();
});

test('referral_copy_and_share_use_only_validated_server_link', async ({ page }) => {
  await mockBase(page);
  const link = 'https://t.me/configured_bot?start=ref_41';
  await page.route('**/referrals/my', route => route.fulfill({ json: { link, invited: 2, confirmed: 1 } }));
  // Только шпионы нативных API; реального clipboard/share или внешней навигации нет.
  await page.addInitScript(() => {
    (window as any).__referralActions = [];
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
      writeText: async (value: string) => { (window as any).__referralActions.push({ kind: 'copy', url: value }); },
    } });
    Object.defineProperty(navigator, 'share', { configurable: true, value: async (data: { url: string }) => {
      (window as any).__referralActions.push({ kind: 'share', url: data.url });
    } });
  });
  await page.goto('/#deposit');
  await expect(page.locator('#reflink')).toHaveValue(link);
  await page.locator('#reflink').evaluate((element: HTMLInputElement) => { element.value = '…'; });
  await page.click('#profile-referrals [data-copy]');
  await page.click('#profile-referrals [data-share]');
  expect(await page.evaluate(() => (window as any).__referralActions)).toEqual([
    { kind: 'copy', url: link }, { kind: 'share', url: link },
  ]);
});

test('mobile_header_keeps_brand_and_balances_separate_without_horizontal_overflow', async ({ page }) => {
  await page.setViewportSize({ width: 388, height: 844 });
  await mockBase(page);
  await page.route('**/wallet', route => route.fulfill({ json: { units_minor: 4000, freebets_units: 500 } }));
  await page.goto('/');
  await expect(page.locator('#view h1')).toHaveText('Caixas');
  await expect(page.locator('#brand-name')).toHaveText('ROBLOXWINDROP');
  await expect(page.locator('#bg')).toHaveText('4.000');
  await expect(page.locator('#bc')).toHaveText('500');
  await expect(page.locator('.logo-img')).toHaveAttribute('src', 'assets/logo-mark.webp?v=70ef005343dd');
  const geometry = await page.locator('.top').evaluate(header => {
    const label = header.querySelector('#brand-name') as HTMLElement;
    const balances = header.querySelector('.bal') as HTMLElement;
    const logo = header.querySelector('.logo-img') as HTMLElement;
    const labelRect = label.getBoundingClientRect(), balanceRect = balances.getBoundingClientRect();
    return { labelRight: labelRect.right, balanceLeft: balanceRect.left, balanceRight: balanceRect.right,
      viewportWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth,
      logoHeight: logo.getBoundingClientRect().height, clipped: label.scrollWidth > label.clientWidth,
      overflow: getComputedStyle(label).overflow, textOverflow: getComputedStyle(label).textOverflow };
  });
  expect(geometry.labelRight).toBeLessThanOrEqual(geometry.balanceLeft - 9);
  expect(geometry.balanceRight).toBeLessThanOrEqual(geometry.viewportWidth - 15);
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.viewportWidth);
  expect(geometry.logoHeight).toBe(28);
  if (geometry.clipped) {
    expect(geometry.textOverflow).toBe('ellipsis');
    expect(geometry.overflow).toBe('hidden');
  }
});

test('profile_history_labels_new_operations_in_portuguese_and_marks_test_balance', async ({ page }) => {
  await mockBase(page);
  const t = new Date().toISOString();
  await page.route('**/wallet/history', route => route.fulfill({ json: [
    { text: 'giftcard_redemption', currency: 'units', delta: -900, t },
    { text: 'welcome_freebet', currency: 'freebets', delta: 500, t },
    { text: 'sandbox_preview', currency: 'units', delta: 5000, t },
  ] }));
  await page.goto('/#deposit');
  await expect(page.locator('#profile-history li b')).toHaveText([
    'Troca por gift card', 'Bônus de boas-vindas em cobre', 'Atualização de saldo',
  ]);
  await expect(page.locator('#profile-history li em')).toHaveText(['-900 ouro', '+500 cobre', '+5.000 ouro']);
});

test('persistent_401_does_not_recursively_authenticate', async ({ page }) => {
  const base = await mockBase(page);
  await page.route('**/wallet', route => route.fulfill({ status: 401, json: { detail: 'invalid_telegram_auth' } }));
  await page.goto('/');
  await expect(page.locator('#view h1')).toHaveText('Abrir pelo Telegram');
  expect(base.authBodies).toHaveLength(2);
  await page.click('.nav [data-tab="profile"]');
  await expect(page.locator('#view h1')).toHaveText('Abrir pelo Telegram');
  expect(base.authBodies).toHaveLength(2);
});
