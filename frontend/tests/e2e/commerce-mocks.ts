import type { Page, Route } from '@playwright/test';

export const QID = 'a'.repeat(32);
export const IID = 'b'.repeat(32);
export const BASE_BOT = 123456;

export function mockJwt(bot = BASE_BOT, account = '41', scope = 'primary') {
  return `header.${Buffer.from(JSON.stringify({ sub: account, auth_bot_id: bot, scope })).toString('base64url')}.test-signature`;
}

export const SDK_SCRIPT = `
window.__invoiceCalls = [];
window.Telegram = { WebApp: {
  initData: 'signed-test-init-data',
  initDataUnsafe: { user: { id: 999999, first_name: 'Teste' }, start_param: '' },
  ready() {}, expand() {}, isVersionAtLeast() { return true; },
  openInvoice(url, callback) { window.__invoiceCalls.push(url); if (callback) callback('paid'); }
} };
`;

export const methodMeta = (mode = 'disabled') => ({ mode, methods: [
  { method: 'stars', rail: 'stars', label: 'Telegram Stars' },
  { method: 'gift', rail: 'gift', label: 'Presente Telegram' },
  { method: 'card', rail: 'paygate', label: 'Cartão' },
  { method: 'crypto', rail: 'paymento', label: 'Criptomoedas' },
].map(row => ({ ...row, mode, enabled: mode !== 'disabled', reason: mode === 'disabled' ? 'Pagamentos desativados pelo servidor.' : '' })) });

export const paymentQuote = (extra = {}) => ({
  quote_id: QID, coins: 100, wallet_unit: 'coin', currency: 'BRL',
  amount_brl_minor: 1234, net_brl_minor: 1234, fee_brl_minor: 66, gross_brl_minor: 1300,
  method: 'card', rail: 'paygate', mode: 'sandbox', channel: 'telegram',
  provider_amount_atomic: '1300', provider_currency: 'BRL', provider_exponent: 2,
  expires_at: new Date(Date.now() + 120000).toISOString(), ...extra,
});
export const paymentIntent = (extra = {}) => ({
  intent_id: IID, quote_id: QID, coins: 100, wallet_unit: 'coin', method: 'card', rail: 'paygate',
  mode: 'sandbox', status: 'pending', client_payload: { action: 'sandbox' }, ...extra,
});
export const SKU = { id: 7, brand: 'Roblox', region: 'BR', card_currency: 'BRL', face_value_minor: 5000,
  coin_cost: 900, sandbox: false, available_count: 3, available: true };
export const redemption = (extra = {}) => ({ id: 51, sku_id: SKU.id, brand: SKU.brand, region: SKU.region,
  card_currency: SKU.card_currency, face_value_minor: SKU.face_value_minor, coin_cost: SKU.coin_cost,
  sandbox: false, status: 'pending', ...extra });

// Все HTTP API/SDK мокаются: тесты не обращаются к реальному backend/Telegram/payment providers.
export async function mockBase(page: Page, options: { bot?: number; account?: string; scope?: string; sdk?: string } = {}) {
  const authBodies: Record<string, unknown>[] = [];
  const unexpected: string[] = [];
  await page.route('https://telegram.org/js/telegram-web-app.js', route => route.fulfill({ contentType: 'application/javascript', body: options.sdk ?? SDK_SCRIPT }));
  const defaults: Record<string, unknown> = {
    '/wallet': { units_minor: 1000, freebets_units: 500 },
    '/meta/tenant': { tenant: 'default', brand: { name: 'ROBLOXWINDROP', logo_url: '', primary_color: '#c8102e' }, domains: {}, geos: ['BR'], games: ['roblox'] },
    '/meta/payment-methods': methodMeta(),
    '/giftcards/catalog': { enabled: false, mode: 'disabled', items: [] },
    '/bots/me': { enabled: true, main_bot_username: 'windrop_bot', managed_bots: [], create_url: 'https://t.me/windrop_bot?start=managed' },
    '/redemptions': [], '/cases': [], '/inventory': [], '/wallet/history': [],
    '/rewards/daily/status': { can_claim: true, streak: 0, claimed_dates: [] },
    '/referrals/my': { link: 'https://t.me/windrop_bot?start=WDTEST', invited: 2, confirmed: 1 },
  };
  await page.route('**/*', async (route: Route) => {
    const url = new URL(route.request().url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) {
      if (url.hostname === 'telegram.org' && url.pathname === '/js/telegram-web-app.js') return route.fallback();
      unexpected.push(`external ${url.href}`); return route.abort();
    }
    const pathname = url.pathname;
    if (pathname === '/auth/telegram') {
      authBodies.push(route.request().postDataJSON());
      return route.fulfill({ json: { access_token: mockJwt(options.bot, options.account, options.scope), token_type: 'bearer' } });
    }
    if (route.request().method() === 'GET' && Object.hasOwn(defaults, pathname)) return route.fulfill({ json: defaults[pathname] });
    if (/^\/(auth|meta|wallet|cases|inventory|games|deposits|payments|withdrawals|redemptions|giftcards|bots|referrals|rewards)(\/|$)/.test(pathname)) {
      unexpected.push(`${route.request().method()} ${pathname}`);
      return route.fulfill({ status: 503, json: { detail: { code: 'service_unavailable' } } });
    }
    return route.fallback();
  });
  return { authBodies, unexpected };
}
