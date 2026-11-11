const { test } = require('node:test');
const assert = require('node:assert/strict');
const { ApiError } = require('../../js/api-client.js');
const { createCommerce, createPoller, formatBrl, formatAtomic, normalizeMethods, normalizeQuote,
  normalizeIntent, normalizeCatalog, normalizeRedemption, safePaymentUrl, safeBotLink, safeReferralLink, navigationTarget } = require('../../js/commerce.js');

const TIME = Date.parse('2026-11-11T12:00:00Z');
const QID = 'a'.repeat(32), IID = 'b'.repeat(32);
const methods = (mode = 'sandbox') => ({ mode, methods: [
  { method: 'stars', rail: 'stars', label: 'Telegram Stars', enabled: true, mode, reason: '' },
  { method: 'gift', rail: 'gift', label: 'Presente Telegram', enabled: true, mode, reason: '' },
  { method: 'card', rail: 'paygate', label: 'Cartão', enabled: true, mode, reason: '' },
  { method: 'crypto', rail: 'paymento', label: 'Criptomoedas', enabled: true, mode, reason: '' },
] });
const quote = (extra = {}) => ({ quote_id: QID, coins: 100, wallet_unit: 'coin', currency: 'BRL', method: 'card', rail: 'paygate',
  mode: 'sandbox', channel: 'telegram', amount_brl_minor: 1234, net_brl_minor: 1234, fee_brl_minor: 66, gross_brl_minor: 1300,
  provider_amount_atomic: '1300', provider_currency: 'BRL', provider_exponent: 2,
  expires_at: new Date(TIME + 60000).toISOString(), ...extra });
const intent = (extra = {}) => ({ intent_id: IID, quote_id: QID, coins: 100, method: 'card', rail: 'paygate', mode: 'sandbox',
  status: 'pending', client_payload: { action: 'sandbox' }, ...extra });
const sku = { id: 7, brand: 'Roblox', region: 'BR', card_currency: 'BRL', face_value_minor: 5000, coin_cost: 900,
  sandbox: true, available_count: 3, available: true };
const order = (extra = {}) => ({ ...sku, id: 51, sku_id: sku.id, status: 'pending', ...extra });
const memory = () => {
  const data = new Map();
  return { data, getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) };
};
function timers() {
  let serial = 0;
  const tasks = new Map();
  return { tasks, setTimer: (fn, delay) => { const id = ++serial; tasks.set(id, { fn, delay }); return id; },
    clearTimer: id => tasks.delete(id), async fireFirst() {
      const first = tasks.entries().next().value;
      if (!first) return;
      tasks.delete(first[0]); await first[1].fn(); await new Promise(resolve => setImmediate(resolve));
    } };
}
function fixture({ route = async () => undefined, store = memory(), key = 'managed:bot:777777:account:41', sdk = {}, clock = () => TIME } = {}) {
  const log = [], timer = timers(); let walletCalls = 0;
  const defaults = {
    '/meta/payment-methods': methods(), '/giftcards/catalog': { enabled: true, mode: 'sandbox', items: [sku] },
    '/redemptions': [], '/bots/me': { enabled: true, main_bot_username: 'windrop_bot', managed_bots: [], create_url: 'https://t.me/windrop_bot?start=managed' },
  };
  const client = { getContext: () => key, getChannel: () => 'telegram', request: async (path, options = {}) => {
    log.push({ path, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null });
    const result = await route(path, options);
    if (result !== undefined) return result;
    if ((options.method || 'GET') === 'GET' && Object.hasOwn(defaults, path)) return structuredClone(defaults[path]);
    throw new Error(`Непредусмотренный запрос ${path}`);
  } };
  const controller = createCommerce({ client, storage: store, getTelegram: () => sdk,
    now: clock, ...timer, visible: () => true, makeNonce: () => 'c'.repeat(32), onWalletChange: () => { walletCalls++; } });
  return { controller, client, log, timer, store, getWalletCalls: () => walletCalls };
}

test('четыре метода по умолчанию выключены и без card/crypto fallback', () => {
  assert.equal(normalizeMethods(null).length, 4);
  assert.ok(normalizeMethods(null).every(m => !m.enabled && m.reason));
  assert.ok(normalizeMethods({ mode: 'disabled', methods: methods().methods }).every(m => !m.enabled));
  const invalid = methods(); invalid.methods[2].rail = 'anything';
  assert.equal(normalizeMethods(invalid).find(m => m.method === 'card').enabled, false);
  const duplicate = methods(); duplicate.methods.push(duplicate.methods[0]);
  assert.equal(normalizeMethods(duplicate)[0].enabled, false);
});

test('BRL cents и атомы форматируются раздельно без потери точности', () => {
  assert.match(formatBrl(1234), /^R\$\s12,34$/);
  assert.equal(formatAtomic('9007199254740993123', 18, 'TEST-USDT'), '9,007199254740993123 TEST-USDT');
  assert.equal(formatAtomic('300', 0, 'XTR'), '300 XTR');
  assert.equal(formatAtomic('123456789012345678', 6, 'USDT'), '123.456.789.012,345678 USDT');
  assert.throws(() => formatAtomic(9007199254740992, 0, 'XTR'));
  assert.throws(() => formatAtomic('1e18', 6, 'USDT'));
  assert.throws(() => formatAtomic('10', 19, 'USDT'));
});

test('котировка проверяет currency, TTL, суммы и выбранный метод; чужие payload поля отбрасываются', () => {
  const normalized = normalizeQuote(quote({ private_key: 'SECRET', address: 'SECRET' }), { method: 'card', coins: 100 }, TIME);
  assert.equal(normalized.provider_amount_atomic, '1300'); assert.equal(normalized.private_key, undefined); assert.equal(normalized.address, undefined);
  assert.throws(() => normalizeQuote(quote({ currency: 'USD' }), null, TIME));
  assert.throws(() => normalizeQuote(quote({ gross_brl_minor: 1500 }), null, TIME));
  assert.throws(() => normalizeQuote(quote(), { method: 'stars' }, TIME));
  assert.throws(() => normalizeQuote(quote({ expires_at: new Date(TIME).toISOString() }), null, TIME), error => error.code === 'quote_expired');
  assert.throws(() => normalizeQuote(quote({ provider_amount_atomic: 9007199254740992 }), null, TIME));
});

test('платёжные ссылки допускают только точный HTTPS allowlist', () => {
  assert.equal(safePaymentUrl('https://t.me/$invoice_123', 'stars'), 'https://t.me/$invoice_123');
  assert.equal(safePaymentUrl('https://t.me/windrop_bot?invoice=abc123', 'stars'), 'https://t.me/windrop_bot?invoice=abc123');
  assert.equal(safePaymentUrl('https://checkout.paygate.to/process-payment.php?amount=13.00', 'paygate'), 'https://checkout.paygate.to/process-payment.php?amount=13.00');
  for (const value of ['javascript:alert(1)', 'http://t.me/$abc', 'https://t.me.evil.test/$abc', 'https://evil@t.me/$abc', 'https://t.me:8080/$abc', 'https://t.me\\evil.test/$abc', 'https://t.me/not-an-invoice', '//t.me/$abc']) {
    assert.equal(safePaymentUrl(value, 'stars'), null, value);
  }
  assert.equal(safePaymentUrl('https://unknown.paymento.io/pay', 'paymento'), null);
  assert.equal(safePaymentUrl('https://checkout.paygate.to.evil.test/process-payment.php', 'paygate'), null);
});

test('личный бот требует t.me с username сервера и точным start=managed', () => {
  assert.equal(safeBotLink('https://t.me/windrop_bot?start=managed', 'windrop_bot', true), 'https://t.me/windrop_bot?start=managed');
  for (const link of ['https://t.me/other_bot?start=managed', 'https://t.me/windrop_bot?start=x', 'https://t.me/windrop_bot?start=managed&token=SECRET', 'https://t.me.evil.test/windrop_bot?start=managed']) {
    assert.equal(safeBotLink(link, 'windrop_bot', true), null);
  }
});

test('пригласительная ссылка принимается только как HTTPS Telegram deep link без фиктивного default', () => {
  assert.equal(safeReferralLink('https://t.me/configured_bot?start=ref_41'), 'https://t.me/configured_bot?start=ref_41');
  for (const value of [undefined, null, '', '…', 'javascript:alert(1)', 'http://t.me/configured_bot?start=ref_41',
    'https://t.me.evil.invalid/configured_bot?start=ref_41', 'https://user@t.me/configured_bot?start=ref_41',
    'https://t.me:8080/configured_bot?start=ref_41', 'https://t.me/configured_bot',
    'https://t.me/configured_bot?start=', 'https://t.me/configured_bot?start=a&start=b',
    'https://t.me/configured_bot?start=ref_41&token=SECRET', 'https://t.me/configured_bot?start=ref_41#secret',
    'https://t.me/configured_bot?start=two%20words', 'https://t.me/configured_bot?start=' + 'a'.repeat(65),
    'https://t.me\\\\evil.invalid/configured_bot?start=ref_41']) {
    assert.equal(safeReferralLink(value), null, String(value));
  }
});

test('deep links используются только для двух маршрутов профиля', () => {
  assert.equal(navigationTarget('#deposit', 'withdraw'), 'deposit');
  assert.equal(navigationTarget('', 'withdraw'), 'withdraw');
  assert.equal(navigationTarget('#unknown', 'deposit'), 'deposit');
  assert.equal(navigationTarget('#user=41', 'auth_bot_id=77'), null);
});

test('quote → explicit confirm → timeout → same key and intent → sandbox не кредитует баланс', async () => {
  let creates = 0, settled = false;
  const f = fixture({ route: async (path, options) => {
    if (path === '/deposits/quote') return quote();
    if (path === '/deposits') { creates++; if (creates === 1) throw new ApiError('network_timeout'); return intent(); }
    if (path.endsWith('/sandbox-settle')) { settled = true; return { status: 'sandbox_succeeded', credited: false }; }
    if (path === `/deposits/${IID}`) return intent({ status: settled ? 'sandbox_succeeded' : 'pending' });
  } });
  await f.controller.load(); f.controller.setMethod('card'); await f.controller.previewDeposit();
  assert.equal(creates, 0); assert.match(f.controller.depositView(), /13,00/);
  await f.controller.confirmDeposit();
  assert.equal(creates, 1); assert.equal(f.controller.getState().deposit.intent, null);
  const before = f.controller.getState().deposit.attempt;
  f.controller.setAmount('500'); f.controller.setMethod('stars');
  assert.equal(f.controller.getState().deposit.amount, '100');
  await f.controller.confirmDeposit();
  const posts = f.log.filter(row => row.path === '/deposits');
  assert.equal(posts.length, 2); assert.deepEqual(posts[0].body, posts[1].body);
  assert.deepEqual(Object.keys(posts[0].body).sort(), ['idempotency_key', 'quote_id']);
  assert.equal(f.controller.getState().deposit.intent.intent_id, IID);
  assert.equal(f.controller.getState().deposit.attempt.nonce, before.nonce);
  assert.equal(settled, false); assert.equal(f.getWalletCalls(), 0);
  const persisted = [...f.store.data.values()].join('');
  assert.ok(!persisted.includes(posts[0].body.idempotency_key)); assert.ok(!persisted.includes('provider_amount'));
  await f.controller.settleSandbox();
  assert.equal(f.controller.getState().deposit.intent.status, 'sandbox_succeeded');
  assert.match(f.controller.depositView(), /Solicitação concluída pelo servidor/);
  assert.equal(f.getWalletCalls(), 0); assert.equal(f.store.data.size, 0);
  f.controller.dispose();
});

test('параллельное подтверждение не создаёт второй POST', async () => {
  let release; const gate = new Promise(resolve => { release = resolve; }); let creates = 0;
  const f = fixture({ route: async path => {
    if (path === '/deposits/quote') return quote();
    if (path === '/deposits') { creates++; await gate; return intent(); }
  } });
  await f.controller.load(); f.controller.setMethod('card'); await f.controller.previewDeposit();
  const first = f.controller.confirmDeposit(); await f.controller.confirmDeposit(); assert.equal(creates, 1);
  release(); await first; f.controller.dispose();
});

test('attempt восстанавливается для того же аккаунта/бота без автоматического POST', async () => {
  const store = memory(); let first = true;
  const route = async path => {
    if (path === '/deposits/quote') return quote();
    if (path === '/deposits') { if (first) { first = false; throw new ApiError('network_timeout'); } return intent(); }
  };
  const initial = fixture({ store, route }); await initial.controller.load(); initial.controller.setMethod('card');
  await initial.controller.previewDeposit(); await initial.controller.confirmDeposit();
  const key = initial.log.find(row => row.path === '/deposits').body.idempotency_key;
  initial.controller.dispose();
  const other = fixture({ store, route, key: 'managed:bot:888888:account:41' }); await other.controller.load();
  assert.equal(other.controller.getState().deposit.attempt, null); other.controller.dispose();
  const otherAccount = fixture({ store, route, key: 'managed:bot:777777:account:42' }); await otherAccount.controller.load();
  assert.equal(otherAccount.controller.getState().deposit.attempt, null); otherAccount.controller.dispose();
  const resumed = fixture({ store, route }); await resumed.controller.load();
  assert.equal(resumed.log.filter(row => row.method === 'POST').length, 0);
  await resumed.controller.confirmDeposit();
  assert.equal(resumed.log.find(row => row.path === '/deposits').body.idempotency_key, key);
  resumed.controller.dispose();
});

test('сумма/метод/expiry и запоздалый quote-response инвалидируют preview', async () => {
  let time = TIME, release;
  const f = fixture({ clock: () => time, route: async path => path === '/deposits/quote' ? quote() : undefined });
  await f.controller.load(); f.controller.setMethod('card'); await f.controller.previewDeposit();
  f.controller.setAmount('500'); assert.equal(f.controller.getState().deposit.quote, null);
  f.controller.setAmount('100'); await f.controller.previewDeposit(); f.controller.setMethod('stars');
  assert.equal(f.controller.getState().deposit.quote, null);
  f.controller.setMethod('card'); await f.controller.previewDeposit(); time += 61000;
  await f.controller.confirmDeposit(); assert.equal(f.log.filter(row => row.path === '/deposits').length, 0);
  f.controller.dispose();
  const gate = new Promise(resolve => { release = resolve; });
  const delayed = fixture({ route: async path => { if (path === '/deposits/quote') { await gate; return quote(); } } });
  await delayed.controller.load(); delayed.controller.setMethod('card'); const preview = delayed.controller.previewDeposit();
  delayed.controller.setAmount('500'); release(); await preview;
  assert.equal(delayed.controller.getState().deposit.quote, null); delayed.controller.dispose();
});

test('disabled или старый API не использует небезопасные endpoints', async () => {
  const f = fixture({ route: async path => {
    if (path === '/meta/payment-methods' || path === '/giftcards/catalog') throw new ApiError('service_unavailable', 404);
  } });
  await f.controller.load(); await f.controller.previewDeposit(); f.controller.previewGift(); await f.controller.confirmGift();
  assert.ok(f.controller.getState().deposit.methods.every(method => !method.enabled));
  assert.equal(f.log.filter(row => row.method === 'POST').length, 0);
  assert.ok(f.log.every(row => !row.path.includes('/meta/geos') && !row.path.startsWith('/withdrawals')));
  assert.match(f.controller.giftView(), /Nenhuma moeda/); f.controller.dispose();
});

test('gift manual review не считается успехом, ссылка с javascript блокируется', async () => {
  const q = quote({ method: 'gift', rail: 'gift', mode: 'live' });
  const f = fixture({ route: async path => {
    if (path === '/meta/payment-methods') return methods('live');
    if (path === '/deposits/quote') return q;
    if (path === '/deposits') return intent({ method: 'gift', rail: 'gift', mode: 'live', client_payload: { action: 'pending_review', payment_url: 'javascript:alert(1)' } });
  } });
  await f.controller.load(); f.controller.setMethod('gift'); await f.controller.previewDeposit(); await f.controller.confirmDeposit();
  assert.match(f.controller.depositView(), /Em análise manual/); assert.doesNotMatch(f.controller.depositView(), /href="javascript:/);
  assert.equal(f.getWalletCalls(), 0); f.controller.dispose();
});

test('Stars требует отдельного явного SDK tap; SDK callback не credit proof', async () => {
  let opens = 0, callback;
  const f = fixture({ sdk: { isVersionAtLeast: () => true, openInvoice: (link, cb) => { opens++; callback = cb; } }, route: async path => {
    if (path === '/meta/payment-methods') return methods('live');
    if (path === '/deposits/quote') return quote({ method: 'stars', rail: 'stars', mode: 'live', provider_amount_atomic: '300', provider_currency: 'XTR', provider_exponent: 0 });
    if (path === '/deposits') return intent({ method: 'stars', rail: 'stars', mode: 'live', client_payload: { action: 'invoice_required' } });
    if (path === '/payments/stars/invoice') return { mode: 'live', invoice_link: 'https://t.me/$invoice_123' };
    if (path === `/deposits/${IID}`) return intent({ method: 'stars', rail: 'stars', mode: 'live', client_payload: { action: 'invoice_required' } });
  } });
  await f.controller.load(); await f.controller.previewDeposit(); await f.controller.confirmDeposit();
  assert.equal(opens, 0); await f.controller.prepareInvoice(); assert.equal(opens, 0);
  f.controller.openInvoice(); assert.equal(opens, 1); callback('paid');
  await new Promise(resolve => setImmediate(resolve)); assert.equal(f.getWalletCalls(), 0);
  assert.equal(f.controller.getState().deposit.intent.status, 'pending'); f.controller.dispose();
});

test('устаревший Telegram SDK не открывает альтернативное окно оплаты', async () => {
  let opens = 0;
  const f = fixture({ sdk: { isVersionAtLeast: () => false, openInvoice: () => { opens++; } }, route: async path => {
    if (path === '/meta/payment-methods') return methods('live');
    if (path === '/deposits/quote') return quote({ method: 'stars', rail: 'stars', mode: 'live' });
    if (path === '/deposits') return intent({ method: 'stars', rail: 'stars', mode: 'live', client_payload: { action: 'invoice_required' } });
    if (path === '/payments/stars/invoice') return { invoice_link: 'https://t.me/$invoice_123' };
  } });
  await f.controller.load(); await f.controller.previewDeposit(); await f.controller.confirmDeposit(); await f.controller.prepareInvoice();
  f.controller.openInvoice(); assert.equal(opens, 0); assert.match(f.controller.depositView(), /Atualize o Telegram/); f.controller.dispose();
});

test('пустой gift catalog блокирует обмен, номинал и стоимость не смешиваются', async () => {
  const f = fixture({ route: async path => path === '/giftcards/catalog' ? { enabled: true, mode: 'live', items: [] } : undefined });
  await f.controller.load(); f.controller.previewGift(); await f.controller.confirmGift();
  assert.equal(f.log.filter(row => row.method === 'POST').length, 0);
  assert.match(f.controller.giftView(), /Nenhum gift card disponível/);
  assert.doesNotMatch(f.controller.giftView(), /wd-count|no cartão/); f.controller.dispose();
  const invalid = normalizeCatalog({ enabled: true, mode: 'live', items: [{ ...sku, sandbox: false, card_currency: 'USD' }] });
  assert.equal(invalid.items.length, 0);
});

test('gift SKU review/confirm отправляет один sku и stable key; codes никогда не хранятся и не выводятся', async () => {
  let calls = 0, done = false;
  const f = fixture({ route: async (path, options) => {
    if (path === '/redemptions' && options.method === 'POST') { calls++; if (calls === 1) throw new ApiError('network_timeout'); return order({ code: 'SECRET-CODE', delivery_payload: { code: 'SECRET-CODE' } }); }
    if (path === '/redemptions/51') return order({ status: done ? 'issued' : 'pending', code: 'SECRET-CODE' });
  } });
  await f.controller.load(); f.controller.previewGift(); assert.equal(calls, 0);
  assert.match(f.controller.giftView(), /50,00/); assert.match(f.controller.giftView(), /900 moedas/);
  await f.controller.confirmGift(); assert.equal(f.getWalletCalls(), 0);
  await f.controller.confirmGift(); await new Promise(resolve => setImmediate(resolve));
  const posts = f.log.filter(row => row.path === '/redemptions' && row.method === 'POST');
  assert.deepEqual(posts[0].body, posts[1].body); assert.deepEqual(Object.keys(posts[0].body).sort(), ['idempotency_key', 'sku_id']);
  assert.equal(posts[0].body.sku_id, 7); assert.equal(f.getWalletCalls(), 1);
  assert.doesNotMatch(JSON.stringify(f.controller.getState()), /SECRET-CODE/);
  assert.doesNotMatch([...f.store.data.values()].join(''), /SECRET-CODE|idempotency_key/);
  done = true; await f.controller.checkGift(); assert.match(f.controller.giftView(), /Envio concluído pelo bot/);
  f.controller.dispose();
});

test('изменение SKU при подтверждении требует нового review и не списывает произвольную сумму', async () => {
  let catalogCalls = 0;
  const f = fixture({ route: async path => {
    if (path === '/giftcards/catalog') { catalogCalls++; return { enabled: true, mode: 'sandbox', items: [{ ...sku, coin_cost: catalogCalls === 1 ? 900 : 1000 }] }; }
  } });
  await f.controller.load(); f.controller.previewGift(); await f.controller.confirmGift();
  assert.equal(f.log.filter(row => row.method === 'POST').length, 0);
  assert.equal(f.controller.getState().gift.preview, null); assert.equal(f.getWalletCalls(), 0); f.controller.dispose();
});

test('неожиданные terminal статусы fail closed и private fields отбрасываются', () => {
  assert.equal(normalizeIntent(intent({ status: 'succeeded' })).status, 'unknown');
  assert.equal(normalizeIntent(intent({ status: 'sandbox_succeeded', mode: 'live' })).status, 'unknown');
  assert.equal(normalizeRedemption(order({ code: 'SECRET', status: 'magic' })).status, 'unknown');
  assert.equal(normalizeRedemption(order({ code: 'SECRET' })).code, undefined);
});

test('ошибки и server labels безопасно экранируются в формах', async () => {
  const malicious = methods(); malicious.methods[0].reason = '<img src=x onerror=alert(1)>'; malicious.methods[0].enabled = false;
  const f = fixture({ route: async path => path === '/meta/payment-methods' ? malicious : undefined });
  await f.controller.load(); assert.match(f.controller.depositView(), /&lt;img/); assert.doesNotMatch(f.controller.depositView(), /<img src=x/);
  f.controller.dispose();
});

test('poller ограничивает запросы, паузится при hidden и не создаёт overlap', async () => {
  let time = TIME, isVisible = true, paused = 0, calls = 0, done = false;
  const timer = timers(); let release;
  const poller = createPoller({ ...timer, now: () => time, visible: () => isVisible, done: () => done,
    maxRequests: 3, interval: 3000, onPause: () => { paused++; }, task: async () => { calls++; } });
  poller.start('intent'); isVisible = false; poller.suspend(); assert.equal(timer.tasks.size, 0);
  await poller.check(); assert.equal(calls, 0); isVisible = true; poller.resume();
  for (let i = 0; i < 3; i++) { time += 3000; await timer.fireFirst(); }
  assert.equal(calls, 3); assert.equal(timer.tasks.size, 0); assert.ok(paused > 0);
  time += 3000; await poller.check(); assert.equal(calls, 3); poller.stop();
  const gate = new Promise(resolve => { release = resolve; }); let overlapping = 0;
  const second = createPoller({ ...timer, now: () => time, visible: () => true, done: () => false,
    task: async () => { overlapping++; await gate; } });
  const pending = second.start('same', true); await second.check(); time += 6000; second.resume();
  assert.equal(overlapping, 1); release(); await pending; second.stop();
});

test('после истечения intent нельзя открыть платёжную ссылку или автоматически завершить sandbox', async () => {
  let time = TIME;
  const f = fixture({ clock: () => time, route: async path => {
    if (path === '/deposits/quote') return quote();
    if (path === '/deposits') return intent();
  } });
  await f.controller.load(); f.controller.setMethod('card'); await f.controller.previewDeposit(); await f.controller.confirmDeposit();
  time += 61000; f.controller.visibilityChanged();
  await f.controller.settleSandbox();
  assert.equal(f.log.filter(row => row.path.endsWith('/sandbox-settle')).length, 0);
  assert.doesNotMatch(f.controller.depositView(), /data-depsandbox/);
  assert.equal(f.controller.allowPaymentLink(), false); f.controller.dispose();
});

test('wallet refresh вызывается только при server live terminal и не доверяет коду провайдера', async () => {
  let terminal = false;
  const f = fixture({ route: async path => {
    if (path === '/meta/payment-methods') return methods('live');
    if (path === '/deposits/quote') return quote({ mode: 'live' });
    if (path === '/deposits') return intent({ mode: 'live', client_payload: { action: 'pending_review', payment_url: 'https://checkout.paygate.to/process-payment.php?amount=13.00' } });
    if (path === `/deposits/${IID}`) return intent({ mode: 'live', status: terminal ? 'succeeded' : 'pending', client_payload: {} });
  } });
  await f.controller.load(); f.controller.setMethod('card'); await f.controller.previewDeposit(); await f.controller.confirmDeposit();
  assert.equal(f.getWalletCalls(), 0); assert.match(f.controller.depositView(), /data-payment-link/);
  terminal = true; await f.controller.checkDeposit(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.getWalletCalls(), 1); assert.match(f.controller.depositView(), /Depósito confirmado pelo servidor/);
  assert.equal(f.store.data.size, 0); f.controller.dispose();
});

test('no_inventory ответ показывает PT причину, освобождает attempt и не меняет баланс', async () => {
  const f = fixture({ route: async (path, options) => {
    if (path === '/redemptions' && options.method === 'POST') throw new ApiError('no_inventory', 409);
  } });
  await f.controller.load(); f.controller.previewGift(); await f.controller.confirmGift();
  assert.match(f.controller.giftView(), /sem estoque/);
  assert.equal(f.controller.getState().gift.attempt, null); assert.equal(f.getWalletCalls(), 0);
  assert.equal(f.store.data.size, 0); f.controller.dispose();
});

test('pending заказ в серверном списке препятствует дубликату после восстановления вкладки', async () => {
  const f = fixture({ route: async path => path === '/redemptions' ? [order()] : undefined });
  await f.controller.load(); f.controller.previewGift(); await f.controller.confirmGift();
  assert.equal(f.controller.getState().gift.preview, null);
  assert.equal(f.log.filter(row => row.method === 'POST').length, 0);
  assert.match(f.controller.giftView(), /Há uma troca em andamento/); f.controller.dispose();
});

test('poller прекращает автоматические попытки после серии ошибок, explicit check ограничен', async () => {
  let time = TIME, calls = 0;
  const timer = timers();
  const poller = createPoller({ ...timer, now: () => time, done: () => false, maxErrors: 2, maxRequests: 4,
    task: async () => { calls++; throw new Error('offline'); } });
  poller.start('pending');
  for (let i = 0; i < 2; i++) { time += 3000; await timer.fireFirst(); }
  assert.equal(calls, 2); assert.equal(timer.tasks.size, 0);
  time += 3000; await poller.check(); assert.equal(calls, 3);
  await poller.check(); assert.equal(calls, 3);
  poller.stop();
});
