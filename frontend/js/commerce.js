/* Безопасные формы профиля. Сервер определяет цены, доступность и итоговый статус. */
(function (root, factory) {
  const api = typeof module === 'object' && module.exports ? require('./api-client.js') : root.WindropApi;
  const commerce = factory(api);
  if (typeof module === 'object' && module.exports) module.exports = commerce;
  else root.WindropCommerce = commerce;
})(globalThis, function (api) {
  'use strict';
  const { ApiError, errorMessage } = api;

  const METHODS = {
    stars: { label: 'Telegram Stars', rail: 'stars' },
    gift: { label: 'Presente Telegram', rail: 'gift' },
    card: { label: 'Cartão', rail: 'paygate' },
    crypto: { label: 'Criptomoedas', rail: 'paymento' },
  };
  const DEPOSIT_STATUS = {
    pending: 'Aguardando confirmação do servidor.',
    pending_review: 'Em análise manual. Nenhum crédito foi confirmado.',
    manual_review: 'Em análise manual. Nenhum crédito foi confirmado.',
    succeeded: 'Depósito confirmado pelo servidor.',
    sandbox_succeeded: 'Solicitação concluída pelo servidor.',
    failed: 'Pagamento não confirmado pelo servidor.',
    expired: 'Pagamento expirado.',
    canceled: 'Pagamento cancelado.',
    cancelled: 'Pagamento cancelado.',
    refunded: 'Reembolso confirmado pelo servidor.',
    unknown: 'Status ainda não reconhecido. Consulte o bot principal antes de tentar novamente.',
  };
  const REDEMPTION_STATUS = {
    pending: 'Pedido recebido. Aguardando envio pelo bot no Telegram.',
    delivering: 'O bot está preparando o envio no Telegram.',
    issued: 'Gift card enviado pelo bot no Telegram.',
    rejected: 'Pedido recusado. Consulte o saldo atualizado pelo servidor.',
    manual_review: 'Pedido em análise manual. Aguarde a equipe pelo Telegram.',
    unknown: 'Status indisponível. Consulte o bot principal antes de fazer outra troca.',
  };
  const TERMINAL_DEPOSIT = new Set(['succeeded', 'sandbox_succeeded', 'failed', 'expired', 'canceled', 'cancelled', 'refunded']);
  const TERMINAL_REDEMPTION = new Set(['issued', 'rejected']);
  const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const text = (value, fallback = '', max = 180) => typeof value === 'string'
    ? value.replace(/[\u0000-\u001f\u007f-\u009f]/g, '').slice(0, max) : fallback;
  const positive = value => Number.isSafeInteger(value) && value > 0;
  const minor = value => Number.isSafeInteger(value) && value >= 0;
  const opaqueId = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
  const modes = new Set(['disabled', 'sandbox', 'live']);
  const count = value => new Intl.NumberFormat('pt-BR').format(value);
  const post = body => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  function atomicDigits(value) {
    if (minor(value)) return String(value);
    if (typeof value === 'string' && /^(0|[1-9]\d{0,39})$/.test(value)) return value;
    throw new ApiError('invalid_response');
  }

  function formatBrl(value) {
    const digits = atomicDigits(value).padStart(3, '0');
    const fraction = digits.slice(-2);
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })
      .formatToParts(BigInt(digits.slice(0, -2)))
      .map(part => part.type === 'fraction' ? fraction : part.value).join('');
  }

  function formatAtomic(value, exponent, currency) {
    const digits = atomicDigits(value);
    if (!Number.isInteger(exponent) || exponent < 0 || exponent > 18 || !/^[A-Z0-9][A-Z0-9._-]{1,23}$/.test(currency)) {
      throw new ApiError('invalid_response');
    }
    if (currency === 'BRL' && exponent === 2) return formatBrl(digits);
    const padded = digits.padStart(exponent + 1, '0');
    const integer = exponent ? padded.slice(0, -exponent) : padded;
    const decimal = exponent ? ',' + padded.slice(-exponent) : '';
    return `${count(BigInt(integer))}${decimal} ${currency}`;
  }

  function normalizeMethods(data) {
    const mode = data && modes.has(data.mode) ? data.mode : 'disabled';
    const rows = data && Array.isArray(data.methods) ? data.methods : [];
    return Object.entries(METHODS).map(([method, defaults]) => {
      const matches = rows.filter(row => row && row.method === method);
      const row = matches.length === 1 ? matches[0] : null;
      const valid = row && row.rail === defaults.rail && row.mode === mode;
      const enabled = !!(valid && mode !== 'disabled' && row.enabled === true);
      return { method, rail: defaults.rail, label: valid ? text(row.label, defaults.label, 50) || defaults.label : defaults.label,
        enabled, mode, reason: enabled ? text(row.reason) : valid && text(row.reason) ||
          (mode === 'disabled' ? 'Pagamentos desativados.' : 'Forma de pagamento indisponível.') };
    });
  }

  function normalizeQuote(data, expected, now = Date.now(), allowExpired = false) {
    if (!data || !opaqueId(data.quote_id) || !positive(data.coins) || data.coins < 100 || data.wallet_unit !== 'coin'
      || data.currency !== 'BRL' || !Object.hasOwn(METHODS, data.method) || data.rail !== METHODS[data.method].rail
      || !['sandbox', 'live'].includes(data.mode) || !['telegram', 'web'].includes(data.channel)
      || ![data.amount_brl_minor, data.net_brl_minor, data.fee_brl_minor, data.gross_brl_minor].every(minor)
      || !positive(data.gross_brl_minor) || data.net_brl_minor + data.fee_brl_minor !== data.gross_brl_minor
      || typeof data.expires_at !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(data.expires_at)) {
      throw new ApiError('invalid_response');
    }
    const expires = Date.parse(data.expires_at);
    if (!Number.isFinite(expires)) throw new ApiError('invalid_response');
    if (!allowExpired && expires <= now) throw new ApiError('quote_expired');
    if (expected && ['coins', 'method', 'mode', 'channel'].some(key => expected[key] !== undefined && expected[key] !== data[key])) {
      throw new ApiError('invalid_response');
    }
    const atomic = atomicDigits(data.provider_amount_atomic);
    if (BigInt(atomic) <= 0n) throw new ApiError('invalid_response');
    formatAtomic(atomic, data.provider_exponent, data.provider_currency);
    // Не сохраняем адреса, payload или конфигурацию, случайно попавшие в DTO.
    return { quote_id: data.quote_id, coins: data.coins, method: data.method, rail: data.rail,
      mode: data.mode, channel: data.channel, amount_brl_minor: data.amount_brl_minor,
      net_brl_minor: data.net_brl_minor, fee_brl_minor: data.fee_brl_minor, gross_brl_minor: data.gross_brl_minor,
      provider_amount_atomic: atomic, provider_currency: data.provider_currency, provider_exponent: data.provider_exponent,
      expires_at: data.expires_at, expires };
  }

  function safePaymentUrl(value, rail) {
    if (typeof value !== 'string' || value.length > 2048 || /[\s\\]/.test(value)) return null;
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.username || url.password || url.port || url.hash) return null;
      if (rail === 'stars' && url.hostname === 't.me' &&
        (/^\/\$[A-Za-z0-9_-]+$/.test(url.pathname) ||
         /^\/[A-Za-z0-9_]{5,32}$/.test(url.pathname) && /^[A-Za-z0-9_-]+$/.test(url.searchParams.get('invoice') || ''))) return url.href;
      if (rail === 'paygate' && url.hostname === 'checkout.paygate.to' && url.pathname === '/process-payment.php') return url.href;
      // Paymento live пока не подключён сервером: неизвестные домены не открываются.
      return null;
    } catch (_) { return null; }
  }

  function safeBotLink(value, username, create = false) {
    if (typeof username !== 'string' || !/^[A-Za-z0-9_]{5,32}$/.test(username) || typeof value !== 'string' || /[\s\\]/.test(value)) return null;
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.hostname !== 't.me' || url.port || url.username || url.password || url.hash
        || url.pathname.toLowerCase() !== '/' + username.toLowerCase()) return null;
      if (create && (url.searchParams.get('start') !== 'managed' || [...url.searchParams].length !== 1)) return null;
      if (!create && url.search) return null;
      return url.href;
    } catch (_) { return null; }
  }

  function safeReferralLink(value) {
    if (typeof value !== 'string' || value.length > 512 || /[\s\\\u0000-\u001f\u007f]/.test(value)) return null;
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.hostname !== 't.me' || url.port || url.username || url.password || url.hash
        || !/^\/[A-Za-z0-9_]{5,32}$/.test(url.pathname) || [...url.searchParams].length !== 1
        || !/^[A-Za-z0-9_-]{1,64}$/.test(url.searchParams.get('start') || '')) return null;
      return url.href;
    } catch (_) { return null; }
  }

  function navigationTarget(hash, startParam) {
    const fromHash = typeof hash === 'string' ? hash.slice(1) : '';
    if (['deposit', 'withdraw'].includes(fromHash)) return fromHash;
    return ['deposit', 'withdraw'].includes(startParam) ? startParam : null;
  }

  function normalizeIntent(data, expected) {
    if (!data || !opaqueId(data.intent_id) || !opaqueId(data.quote_id) || !positive(data.coins)
      || !Object.hasOwn(METHODS, data.method) || data.rail !== METHODS[data.method].rail || !['live', 'sandbox'].includes(data.mode)) throw new ApiError('invalid_response');
    if (expected && (expected.quoteId !== data.quote_id || expected.intentId && expected.intentId !== data.intent_id
      || expected.method !== data.method || expected.coins !== data.coins || expected.mode !== data.mode)) throw new ApiError('invalid_response');
    let status = Object.hasOwn(DEPOSIT_STATUS, data.status) ? data.status : 'unknown';
    if (data.mode === 'sandbox' && status === 'succeeded' || data.mode === 'live' && status === 'sandbox_succeeded') status = 'unknown';
    const payload = data.client_payload || {};
    const rawPaymentUrl = typeof payload.payment_url === 'string' ? payload.payment_url : '';
    const quote = data.quote ? normalizeQuote(data.quote, { coins: data.coins, method: data.method, mode: data.mode }, Date.now(), true) : null;
    const expires = quote?.expires ?? Date.parse(data.expires_at);
    return { intent_id: data.intent_id, quote_id: data.quote_id, coins: data.coins, method: data.method,
      rail: data.rail, mode: data.mode, status, expires: Number.isFinite(expires) ? expires : null,
      action: ['sandbox', 'invoice_required', 'open_invoice', 'pending_review'].includes(payload.action) ? payload.action : '',
      payment_url: safePaymentUrl(rawPaymentUrl, data.rail),
      unsafe_url: !!rawPaymentUrl && !safePaymentUrl(rawPaymentUrl, data.rail), quote };
  }

  function normalizeCatalog(data) {
    if (!data || typeof data.enabled !== 'boolean' || !modes.has(data.mode) || !Array.isArray(data.items)) throw new ApiError('invalid_response');
    const items = data.items.slice(0, 500).filter(row => row && positive(row.id) && positive(row.coin_cost)
      && positive(row.face_value_minor) && row.card_currency === 'BRL' && typeof row.sandbox === 'boolean'
      && minor(row.available_count)).map(row => ({ id: row.id, brand: text(row.brand, 'Gift card', 60),
        region: text(row.region, '', 12), card_currency: 'BRL', face_value_minor: row.face_value_minor,
        coin_cost: row.coin_cost, sandbox: row.sandbox, available_count: row.available_count,
        available: data.enabled && data.mode !== 'disabled' && row.available === true && row.available_count > 0
          && row.sandbox === (data.mode === 'sandbox') }));
    return { mode: data.mode, enabled: data.enabled && data.mode !== 'disabled', items };
  }

  function normalizeRedemption(data) {
    if (!data || !positive(data.id) || !positive(data.sku_id) || !positive(data.coin_cost)
      || !positive(data.face_value_minor) || data.card_currency !== 'BRL' || typeof data.sandbox !== 'boolean') throw new ApiError('invalid_response');
    return { id: data.id, sku_id: data.sku_id, brand: text(data.brand, 'Gift card', 60), region: text(data.region, '', 12),
      card_currency: 'BRL', face_value_minor: data.face_value_minor, coin_cost: data.coin_cost, sandbox: data.sandbox,
      status: Object.hasOwn(REDEMPTION_STATUS, data.status) ? data.status : 'unknown' };
  }

  function normalizeBots(data) {
    if (!data || typeof data.enabled !== 'boolean' || !Array.isArray(data.managed_bots)) throw new ApiError('invalid_response');
    const username = typeof data.main_bot_username === 'string' && /^[A-Za-z0-9_]{5,32}$/.test(data.main_bot_username) ? data.main_bot_username : '';
    return { enabled: data.enabled, main_bot_username: username,
      create_url: data.enabled ? safeBotLink(data.create_url, username, true) : null,
      managed_bots: data.managed_bots.slice(0, 30).filter(row => row && positive(row.bot_id) && /^[A-Za-z0-9_]{5,32}$/.test(row.username))
        .map(row => ({ bot_id: row.bot_id, username: row.username, status: text(row.status, '', 30) })) };
  }

  // Отдельные одноразовые таймеры, без overlap и без связи с игровыми gameTimers.
  function createPoller({ task, done, visible = () => true, onPause = () => {}, now = Date.now,
    setTimer = setTimeout, clearTimer = clearTimeout, interval = 3000, maxRequests = 30, maxErrors = 3, maxDuration = 180000 }) {
    let identity = null, timer = null, running = false, inFlight = false, requests = 0, errors = 0, started = 0, last = -Infinity, generation = 0;
    const clear = () => { if (timer !== null) clearTimer(timer); timer = null; };
    const allowed = manual => running && visible() && !inFlight && !done() && requests < maxRequests
      && (manual || errors < maxErrors && now() - started < maxDuration);
    function schedule(delay = interval) {
      clear();
      if (!running || done()) return;
      if (!allowed(false)) { if (visible() && !inFlight) onPause(); return; }
      timer = setTimer(() => { timer = null; void tick(false); }, delay);
    }
    async function tick(manual) {
      if (!allowed(manual) || manual && now() - last < interval) return false;
      clear(); inFlight = true; requests++; last = now();
      const version = generation;
      try { await task(); if (version === generation) errors = 0; }
      catch (_) { if (version === generation) errors++; }
      finally {
        inFlight = false;
        if (version === generation) schedule();
      }
      return true;
    }
    return {
      start(id, immediate = false) {
        if (identity !== id) { clear(); identity = id; requests = 0; errors = 0; started = now(); last = -Infinity; generation++; }
        running = true;
        if (immediate) return tick(false);
        schedule();
      },
      check: () => tick(true),
      suspend: clear,
      resume: () => schedule(Math.max(0, interval - (now() - last))),
      stop() { clear(); running = false; generation++; },
      getStats: () => ({ requests, errors, inFlight, running, canCheck: running && requests < maxRequests && !done() }),
    };
  }

  function createCommerce({ client, storage, getTelegram = () => globalThis.Telegram && globalThis.Telegram.WebApp,
    onChange = () => {}, onWalletChange = () => {}, visible = () => !globalThis.document?.hidden,
    now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout,
    makeNonce = () => globalThis.crypto.randomUUID().replace(/-/g, '') }) {
    const deposit = { methods: normalizeMethods(null), amount: '100', method: null, quote: null, intent: null,
      attempt: null, busy: false, quoting: false, error: '', notice: '', invoiceLink: null, loaded: false };
    const gift = { catalog: { enabled: false, mode: 'disabled', items: [] }, selected: '', preview: null,
      attempt: null, order: null, orders: [], busy: false, error: '', listError: '', notice: '', loaded: false };
    const openReviewOrders = () => gift.orders.some(order => !TERMINAL_REDEMPTION.has(order.status));
    const depositIsExpired = () => {
      const expires = deposit.quote?.expires ?? deposit.intent?.expires;
      return Number.isFinite(expires) && expires <= now();
    };
    const bots = { enabled: false, main_bot_username: '', managed_bots: [], create_url: null, loaded: false, error: '' };
    let loadPromise = null, lastLoad = -Infinity, restored = false, context = null, quoteTimer = null, quoteVersion = 0;
    const notify = section => onChange(section);
    const request = (path, options) => client.request(path, options);
    const wallet = () => { Promise.resolve().then(onWalletChange).catch(() => {}); };
    const ensureContext = () => {
      if (context !== client.getContext()) throw new ApiError('session_changed', 401);
    };
    const storageKey = kind => context ? `windrop:commerce:v1:${context}:${kind}` : null;
    function persist(kind, attempt) {
      const key = storageKey(kind);
      if (!key) return false;
      try {
        if (attempt) storage.setItem(key, JSON.stringify({ version: 1, ...attempt }));
        else storage.removeItem(key);
        return true;
      } catch (_) { return false; }
    }
    function readAttempt(kind) {
      try {
        const raw = storage && storageKey(kind) && storage.getItem(storageKey(kind));
        if (!raw || raw.length > 2048) return null;
        const a = JSON.parse(raw);
        if (a.version !== 1 || !/^[a-f0-9]{32}$/.test(a.nonce) || !Number.isSafeInteger(a.createdAt)
          || a.createdAt > now() + 60000 || now() - a.createdAt > 7 * 86400000) return null;
        if (kind === 'deposit' && opaqueId(a.quoteId) && positive(a.coins) && METHODS[a.method]
          && ['sandbox', 'live'].includes(a.mode) && (a.intentId === null || opaqueId(a.intentId))) {
          return { nonce: a.nonce, createdAt: a.createdAt, quoteId: a.quoteId, intentId: a.intentId,
            coins: a.coins, method: a.method, mode: a.mode };
        }
        if (kind === 'gift' && positive(a.skuId) && (a.orderId === null || positive(a.orderId))) {
          return { nonce: a.nonce, createdAt: a.createdAt, skuId: a.skuId, orderId: a.orderId };
        }
      } catch (_) {}
      return null;
    }
    function nonce() {
      const value = makeNonce();
      if (typeof value !== 'string' || !/^[a-f0-9]{32}$/.test(value)) throw new ApiError('service_unavailable');
      return value;
    }
    function clearQuote() {
      quoteVersion++;
      if (quoteTimer !== null) clearTimer(quoteTimer);
      quoteTimer = null; deposit.quote = null; deposit.quoting = false;
    }
    const expireNotice = 'A cotação expirou. Não efetue o pagamento; consulte o status da solicitação.';
    function armQuote(quote) {
      if (quoteTimer !== null) clearTimer(quoteTimer);
      if (quote.expires <= now()) return;
      quoteTimer = setTimer(() => {
        quoteTimer = null;
        if (deposit.quote !== quote) return;
        if (deposit.attempt || deposit.intent) { deposit.notice = expireNotice; notify('deposit'); return; }
        clearQuote(); deposit.error = errorMessage(new ApiError('quote_expired')); notify('deposit');
      }, Math.min(2147483647, Math.max(0, quote.expires - now())));
    }

    function applyIntent(data) {
      const intent = normalizeIntent(data, deposit.attempt);
      ensureContext();
      const previous = deposit.intent;
      deposit.intent = intent;
      if (intent.quote) { deposit.quote = intent.quote; armQuote(intent.quote); }
      if (deposit.attempt) { deposit.attempt.intentId = intent.intent_id; persist('deposit', deposit.attempt); }
      if (TERMINAL_DEPOSIT.has(intent.status)) {
        depositPoll.stop(); persist('deposit', null); deposit.attempt = null; deposit.notice = '';
        if (quoteTimer !== null) clearTimer(quoteTimer);
        quoteTimer = null;
        if (intent.mode === 'live' && ['succeeded', 'refunded'].includes(intent.status)
          && (!previous || previous.status !== intent.status)) wallet();
      }
      notify('deposit');
    }
    function applyOrder(data) {
      const order = normalizeRedemption(data);
      ensureContext();
      if (gift.attempt && (gift.attempt.skuId !== order.sku_id || gift.attempt.orderId && gift.attempt.orderId !== order.id)) throw new ApiError('invalid_response');
      const previous = gift.order;
      gift.order = order;
      gift.orders = [order, ...gift.orders.filter(row => row.id !== order.id)].slice(0, 20);
      if (gift.attempt) { gift.attempt.orderId = order.id; persist('gift', gift.attempt); }
      if (TERMINAL_REDEMPTION.has(order.status)) { giftPoll.stop(); persist('gift', null); gift.attempt = null; gift.notice = ''; }
      if (!previous || previous.id !== order.id || previous.status !== order.status) wallet();
      notify('gift');
    }
    const pollOptions = { visible, now, setTimer, clearTimer };
    const depositPoll = createPoller({ ...pollOptions,
      done: () => !!deposit.intent && TERMINAL_DEPOSIT.has(deposit.intent.status),
      onPause() { deposit.notice = 'Atualização automática pausada. Confira o status ou consulte o bot principal.'; notify('deposit'); },
      async task() {
        const id = deposit.attempt?.intentId || deposit.intent?.intent_id;
        if (!id) return;
        try { ensureContext(); const data = await request(`/deposits/${encodeURIComponent(id)}`);
          applyIntent(data); deposit.error = ''; notify('deposit'); }
        catch (error) { deposit.error = errorMessage(error); notify('deposit'); throw error; }
      },
    });
    const giftPoll = createPoller({ ...pollOptions,
      done: () => !!gift.order && TERMINAL_REDEMPTION.has(gift.order.status),
      onPause() { gift.notice = 'Atualização automática pausada. Consulte o status ou o bot principal.'; notify('gift'); },
      async task() {
        const id = gift.attempt?.orderId || gift.order?.id;
        if (!id) return;
        try { ensureContext(); const data = await request(`/redemptions/${id}`); applyOrder(data); gift.error = ''; notify('gift'); }
        catch (error) { gift.error = errorMessage(error); notify('gift'); throw error; }
      },
    });

    function restore() {
      if (restored) return;
      context = client.getContext(); restored = true;
      deposit.attempt = readAttempt('deposit'); gift.attempt = readAttempt('gift');
      if (deposit.attempt) {
        deposit.amount = String(deposit.attempt.coins); deposit.method = deposit.attempt.method;
        deposit.notice = 'Solicitação anterior recuperada. Não faça outro pagamento antes de conferir o resultado.';
        if (deposit.attempt.intentId) void depositPoll.start(deposit.attempt.intentId, true);
      }
      if (gift.attempt) {
        gift.selected = String(gift.attempt.skuId);
        gift.notice = 'Solicitação anterior recuperada. A repetição usa a mesma tentativa.';
        if (gift.attempt.orderId) void giftPoll.start(gift.attempt.orderId, true);
      }
    }

    async function load(force = false) {
      if (loadPromise) return loadPromise;
      if (!force && now() - lastLoad < 30000) return;
      restore();
      const jobs = [
        (async () => {
          try { const data = await request('/meta/payment-methods');
            if (!data || !Array.isArray(data.methods) || !modes.has(data.mode)) throw new ApiError('invalid_response');
            deposit.methods = normalizeMethods(data);
            if (!deposit.attempt && !deposit.intent && !deposit.methods.some(m => m.enabled && m.method === deposit.method)) {
              deposit.method = deposit.methods.find(m => m.enabled)?.method || null; clearQuote();
            }
            if (deposit.quote && !deposit.attempt && !deposit.methods.some(m => m.enabled && m.method === deposit.quote.method && m.mode === deposit.quote.mode)) clearQuote();
            deposit.error = '';
          } catch (error) { deposit.methods = normalizeMethods(null); deposit.error = errorMessage(error); if (!deposit.attempt && !deposit.intent) clearQuote(); }
          deposit.loaded = true; notify('deposit');
        })(),
        (async () => {
          try { gift.catalog = normalizeCatalog(await request('/giftcards/catalog'));
            if (!gift.attempt && !gift.order && !gift.catalog.items.some(item => item.available && String(item.id) === gift.selected)) {
              gift.selected = String(gift.catalog.items.find(item => item.available)?.id || ''); gift.preview = null;
            }
            if (gift.preview && !gift.catalog.items.some(item => item.available && item.id === gift.preview.id
              && item.coin_cost === gift.preview.coin_cost && item.face_value_minor === gift.preview.face_value_minor)) gift.preview = null;
            gift.error = '';
          } catch (error) { gift.catalog = { enabled: false, mode: 'disabled', items: [] }; gift.preview = null; gift.error = errorMessage(error); }
          gift.loaded = true; notify('gift');
        })(),
        (async () => {
          try {
            const data = await request('/redemptions');
            const rows = Array.isArray(data) ? data : data && data.items;
            if (!Array.isArray(rows)) throw new ApiError('invalid_response');
            const orders = rows.slice(0, 20).map(normalizeRedemption);
            gift.orders = gift.order ? [gift.order, ...orders.filter(order => order.id !== gift.order.id)].slice(0, 20) : orders;
            gift.listError = '';
          } catch (error) { gift.listError = errorMessage(error); }
          notify('gift');
        })(),
        (async () => {
          try { Object.assign(bots, normalizeBots(await request('/bots/me')), { error: '' }); }
          catch (error) { Object.assign(bots, { enabled: false, create_url: null, managed_bots: [], error: errorMessage(error) }); }
          bots.loaded = true; notify('bots');
        })(),
      ];
      loadPromise = Promise.all(jobs).finally(() => { lastLoad = now(); loadPromise = null; });
      return loadPromise;
    }

    function setAmount(value) {
      if (deposit.attempt || deposit.intent || deposit.busy) return;
      deposit.amount = String(value); clearQuote(); deposit.error = ''; notify('deposit');
    }
    function setMethod(value) {
      if (deposit.attempt || deposit.intent || deposit.busy || !deposit.methods.some(m => m.method === value && m.enabled)) return;
      deposit.method = value; clearQuote(); deposit.error = ''; notify('deposit');
    }
    async function previewDeposit() {
      if (deposit.busy || deposit.quoting || deposit.attempt || deposit.intent) return;
      clearQuote(); deposit.error = '';
      const selected = deposit.methods.find(m => m.method === deposit.method && m.enabled);
      const coins = /^\d+$/.test(deposit.amount) ? Number(deposit.amount) : NaN;
      if (!positive(coins) || coins < 100 || coins > 100000000) { deposit.error = errorMessage(new ApiError('invalid_coins')); notify('deposit'); return; }
      if (!selected) { deposit.error = errorMessage(new ApiError('method_disabled')); notify('deposit'); return; }
      const version = quoteVersion;
      deposit.quoting = true; notify('deposit');
      try {
        ensureContext();
        const channel = client.getChannel();
        const data = await request('/deposits/quote', post({ coins, method: selected.method, channel }));
        if (version !== quoteVersion) return;
        const quote = normalizeQuote(data, { coins, method: selected.method, channel, mode: selected.mode }, now());
        ensureContext(); deposit.quote = quote; armQuote(quote);
      } catch (error) { if (version === quoteVersion) deposit.error = errorMessage(error); }
      finally { if (version === quoteVersion) { deposit.quoting = false; notify('deposit'); } }
    }
    async function confirmDeposit() {
      if (deposit.busy || deposit.intent) return;
      deposit.error = '';
      try {
        ensureContext();
        if (!deposit.attempt) {
          const quote = deposit.quote;
          if (!quote || quote.expires <= now()) { clearQuote(); throw new ApiError('quote_expired'); }
          if (Number(deposit.amount) !== quote.coins || deposit.method !== quote.method
            || !deposit.methods.some(m => m.enabled && m.method === quote.method && m.mode === quote.mode)) throw new ApiError('method_disabled');
          deposit.attempt = { nonce: nonce(), createdAt: now(), quoteId: quote.quote_id, intentId: null,
            coins: quote.coins, method: quote.method, mode: quote.mode };
          if (!persist('deposit', deposit.attempt)) deposit.notice = 'A recuperação após fechar esta aba não está disponível. Mantenha a aba aberta até confirmar o status.';
        }
        deposit.busy = true; notify('deposit');
        const attempt = deposit.attempt;
        const data = await request('/deposits', post({ quote_id: attempt.quoteId, idempotency_key: `deposit-${attempt.nonce}` }));
        applyIntent(data);
        if (!TERMINAL_DEPOSIT.has(deposit.intent.status)) depositPoll.start(deposit.intent.intent_id);
      } catch (error) {
        deposit.error = errorMessage(error);
        // Только однозначный ответ сервера разрешает отказаться от ещё не созданного intent.
        if (['quote_expired', 'quote_not_found'].includes(error.code) && error.status >= 400) {
          deposit.attempt = null; persist('deposit', null); clearQuote();
        }
      } finally { deposit.busy = false; notify('deposit'); }
    }
    async function settleSandbox() {
      const intent = deposit.intent;
      if (deposit.busy || !intent || intent.mode !== 'sandbox' || intent.status !== 'pending' || intent.action !== 'sandbox') return;
      if (depositIsExpired()) { deposit.error = expireNotice; notify('deposit'); return; }
      deposit.busy = true; deposit.error = ''; notify('deposit');
      try { ensureContext(); await request(`/deposits/${encodeURIComponent(intent.intent_id)}/sandbox-settle`, post({}));
        deposit.notice = 'Simulação solicitada. Aguardando o status do servidor; não é um pagamento real.';
        await depositPoll.check();
      } catch (error) { deposit.error = errorMessage(error); }
      finally { deposit.busy = false; notify('deposit'); }
    }
    async function prepareInvoice() {
      const intent = deposit.intent;
      if (deposit.busy || !intent || intent.method !== 'stars' || intent.mode !== 'live' || intent.status !== 'pending') return;
      if (depositIsExpired()) { deposit.error = expireNotice; notify('deposit'); return; }
      deposit.busy = true; deposit.error = ''; notify('deposit');
      try { ensureContext();
        const data = await request('/payments/stars/invoice', post({ intent_id: intent.intent_id }));
        if (!data || data.action === 'sandbox' || data.mode && data.mode !== 'live'
          || data.intent_id && data.intent_id !== intent.intent_id || deposit.intent?.status !== 'pending' || depositIsExpired()) throw new ApiError('invalid_response');
        ensureContext();
        const link = safePaymentUrl(data && data.invoice_link, 'stars');
        if (!link) throw new ApiError('invalid_response');
        deposit.invoiceLink = link;
      } catch (error) { deposit.error = errorMessage(error); }
      finally { deposit.busy = false; notify('deposit'); }
    }
    function openInvoice() {
      const intent = deposit.intent;
      if (!intent || intent.mode !== 'live' || intent.method !== 'stars' || intent.status !== 'pending'
        || !safePaymentUrl(deposit.invoiceLink, 'stars')) return;
      if (depositIsExpired()) { deposit.error = expireNotice; notify('deposit'); return; }
      try {
        ensureContext();
        const sdk = getTelegram();
        if (!sdk || typeof sdk.openInvoice !== 'function' || typeof sdk.isVersionAtLeast !== 'function' || !sdk.isVersionAtLeast('6.1')) {
          deposit.error = 'Atualize o Telegram e abra a Mini App novamente pelo bot principal para pagar com Stars.'; notify('deposit'); return;
        }
        // Callback SDK не подтверждает оплату: только GET status может подтвердить зачисление.
        sdk.openInvoice(deposit.invoiceLink, () => {
          deposit.notice = 'Aguardando confirmação do servidor. Não pague a mesma solicitação novamente.';
          notify('deposit'); void depositPoll.check();
        });
      } catch (_) { deposit.error = 'Não foi possível abrir a fatura. Abra novamente pelo bot principal no Telegram.'; notify('deposit'); }
    }
    function newDeposit() {
      if (deposit.busy || deposit.attempt || deposit.intent && !TERMINAL_DEPOSIT.has(deposit.intent.status)) return;
      depositPoll.stop(); clearQuote(); deposit.intent = null; deposit.invoiceLink = null; deposit.error = ''; deposit.notice = ''; notify('deposit');
    }
    function setSku(value) {
      if (gift.busy || gift.attempt || gift.order) return;
      gift.selected = String(value); gift.preview = null; gift.error = ''; notify('gift');
    }
    function previewGift() {
      if (gift.busy || gift.attempt || gift.order || openReviewOrders()) return;
      const sku = gift.catalog.items.find(item => String(item.id) === gift.selected && item.available);
      if (!sku || !gift.catalog.enabled) { gift.error = 'Nenhum gift card disponível. Nenhuma moeda foi gasta.'; notify('gift'); return; }
      gift.preview = { ...sku }; gift.error = ''; notify('gift');
    }
    async function confirmGift() {
      if (gift.busy || gift.order) return;
      gift.busy = true; gift.error = ''; notify('gift');
      try {
        ensureContext();
        if (!gift.attempt) {
          if (openReviewOrders()) throw new ApiError('idempotency_conflict');
          const preview = gift.preview;
          if (!preview) throw new ApiError('sku_unavailable');
          const current = normalizeCatalog(await request('/giftcards/catalog'));
          gift.catalog = current;
          const sku = current.items.find(item => item.id === preview.id && item.available);
          if (!current.enabled || !sku || sku.coin_cost !== preview.coin_cost || sku.face_value_minor !== preview.face_value_minor || sku.sandbox !== preview.sandbox) {
            gift.preview = null; throw new ApiError('sku_unavailable');
          }
          gift.attempt = { nonce: nonce(), createdAt: now(), skuId: sku.id, orderId: null };
          if (!persist('gift', gift.attempt)) gift.notice = 'Mantenha esta aba aberta: a recuperação local está indisponível.';
        }
        const attempt = gift.attempt;
        const data = await request('/redemptions', post({ sku_id: attempt.skuId, idempotency_key: `gift-${attempt.nonce}` }));
        applyOrder(data); gift.preview = null;
        if (!TERMINAL_REDEMPTION.has(gift.order.status)) giftPoll.start(gift.order.id);
      } catch (error) {
        gift.error = errorMessage(error);
        if (['sku_unavailable', 'out_of_stock', 'no_inventory', 'insufficient_balance'].includes(error.code) && error.status >= 400) {
          gift.attempt = null; persist('gift', null); gift.preview = null;
        }
      } finally { gift.busy = false; notify('gift'); }
    }
    function newGift() {
      if (gift.busy || gift.attempt || gift.order && !TERMINAL_REDEMPTION.has(gift.order.status)) return;
      giftPoll.stop(); gift.order = null; gift.preview = null; gift.error = ''; gift.notice = ''; notify('gift'); void load(true);
    }
    async function inspectOrder(id) {
      if (!positive(Number(id)) || gift.busy || gift.attempt || gift.order && !TERMINAL_REDEMPTION.has(gift.order.status)) return;
      gift.busy = true; gift.error = ''; notify('gift');
      try { ensureContext();
        const data = await request(`/redemptions/${Number(id)}`);
        if (data.id !== Number(id)) throw new ApiError('invalid_response');
        applyOrder(data);
        if (!TERMINAL_REDEMPTION.has(gift.order.status)) giftPoll.start(gift.order.id);
      } catch (error) { gift.error = errorMessage(error); }
      finally { gift.busy = false; notify('gift'); }
    }

    const message = value => value ? `<p class="form-error" role="alert">${escape(value)}</p>` : '';
    const notice = value => value ? `<p class="form-note" role="status">${escape(value)}</p>` : '';
    function quoteView(quote) {
      if (!quote) return '';
      return `<div class="commerce-preview" id="dep-preview"><h3>Prévia do servidor</h3><dl class="form-summary">
        <dt>Moedas a receber</dt><dd>${count(quote.coins)} moedas</dd>
        <dt>Valor em reais</dt><dd>${formatBrl(quote.net_brl_minor)}</dd>
        <dt>Taxa</dt><dd>${formatBrl(quote.fee_brl_minor)}</dd>
        <dt>Total em reais</dt><dd>${formatBrl(quote.gross_brl_minor)}</dd>
        <dt>Cobrança do provedor</dt><dd>${escape(formatAtomic(quote.provider_amount_atomic, quote.provider_exponent, quote.provider_currency))}</dd>
        </dl><p class="form-note">Válida até ${escape(new Date(quote.expires).toLocaleString('pt-BR'))}. Nenhum pagamento é feito nesta prévia.</p>
        ${quote.mode === 'sandbox' ? notice('A confirmação depende do servidor e do canal autorizado.') : ''}</div>`;
    }
    function mainBotLink() {
      const link = safeBotLink(`https://t.me/${bots.main_bot_username}`, bots.main_bot_username);
      return link ? `<a class="ghost" href="${escape(link)}" target="_blank" rel="noopener noreferrer">Abrir bot principal</a>` : '';
    }
    function depositView() {
      const locked = !!(deposit.attempt || deposit.intent || deposit.busy);
      const enabled = deposit.methods.some(m => m.enabled);
      const intent = deposit.intent;
      const pending = intent && !TERMINAL_DEPOSIT.has(intent.status);
      const expired = depositIsExpired();
      let actions = '';
      if (intent) {
        let status = DEPOSIT_STATUS[intent.status];
        if (intent.method === 'gift' && intent.status === 'pending' && intent.mode === 'live') status = DEPOSIT_STATUS.pending_review;
        actions += `<div id="dep-status" class="commerce-preview" role="status"><strong>${escape(status)}</strong><p class="form-note">Solicitação ${escape(intent.intent_id)} · ${count(intent.coins)} moedas</p></div>`;
        if (intent.mode === 'sandbox') actions += notice('A confirmação depende do servidor e do canal autorizado.');
        if (!expired && intent.mode === 'sandbox' && intent.status === 'pending' && intent.action === 'sandbox') actions += `<button class="cta" data-depsandbox ${deposit.busy ? 'disabled' : ''}>Concluir confirmação</button>`;
        if (!expired && intent.mode === 'live' && intent.method === 'stars' && intent.status === 'pending') {
          actions += deposit.invoiceLink
            ? '<button class="cta" data-depopeninvoice>Abrir fatura Stars no Telegram</button>'
            : `<button class="cta" data-depinvoice ${deposit.busy ? 'disabled' : ''}>Preparar fatura Stars</button>`;
          actions += mainBotLink();
        }
        if (!expired && intent.mode === 'live' && pending && intent.payment_url) actions += `<a class="cta" data-payment-link href="${escape(intent.payment_url)}" target="_blank" rel="noopener noreferrer">Abrir pagamento</a>`;
        if (pending && expired) actions += notice(expireNotice);
        if (intent.unsafe_url) actions += message('O link de pagamento não foi validado. Não abra links alternativos; consulte o bot principal.');
        if (pending) actions += `<button class="ghost" data-depcheck ${deposit.busy || !depositPoll.getStats().canCheck ? 'disabled' : ''}>Consultar status do depósito</button>`;
        else actions += '<button class="ghost" data-depnew>Preparar outro depósito</button>';
      } else if (deposit.attempt) {
        actions += notice(deposit.attempt.intentId ? 'Consultando a solicitação anterior. Não repita o pagamento.' : 'O resultado da confirmação ainda é desconhecido. Repetir usa a mesma solicitação, sem criar uma nova tentativa.');
        actions += deposit.attempt.intentId
          ? `<button class="ghost" data-depcheck ${deposit.busy || !depositPoll.getStats().canCheck ? 'disabled' : ''}>Consultar status do depósito</button>`
          : `<button class="cta" data-depconfirm ${deposit.busy ? 'disabled' : ''}>${deposit.busy ? 'Confirmando…' : 'Repetir confirmação com segurança'}</button>`;
      } else if (deposit.quote && deposit.quote.expires > now()) {
        actions += `<button class="cta" data-depconfirm ${deposit.busy ? 'disabled' : ''}>${deposit.quote.mode === 'sandbox' ? 'Confirmar depósito' : 'Confirmar depósito'}</button>`;
      }
      return `<div class="card-head"><h2>Depositar</h2><span class="pill">mín. 100 moedas</span></div>
        <p class="form-note">O preço e as taxas são informados pelo servidor antes da confirmação.</p>
        <div class="payment-methods" id="deposit-methods">${deposit.methods.map(m => `<div class="payment-option"><button class="chip dep-method${m.method === deposit.method ? ' on' : ''}" data-depmethod="${m.method}" aria-pressed="${m.method === deposit.method}" aria-describedby="dep-reason-${m.method}" ${locked || !m.enabled ? 'disabled' : ''}>${escape(m.label)}</button><small id="dep-reason-${m.method}">${escape(m.reason || (m.mode === 'sandbox' ? 'Disponível neste ambiente.' : 'Disponível.'))}</small></div>`).join('')}</div>
        <div class="controls"><label for="dep-amount">Quantidade de moedas<input id="dep-amount" type="number" min="100" max="100000000" step="1" inputmode="numeric" value="${escape(deposit.amount)}" ${locked ? 'disabled' : ''}></label></div>
        <div class="row">${[100, 500, 1000, 5000].map(n => `<button class="chip" data-dep="${n}" ${locked ? 'disabled' : ''}>${count(n)}</button>`).join('')}</div>
        ${!locked ? `<button class="cta" data-depquote ${!enabled || deposit.quoting ? 'disabled' : ''}>${deposit.quoting ? 'Consultando preço…' : 'Ver prévia do depósito'}</button>` : ''}
        ${!deposit.loaded ? notice('Consultando formas de pagamento…') : !enabled ? notice('Nenhuma forma de pagamento disponível. Nada será cobrado.') : ''}
        ${quoteView(deposit.quote)}${actions}${message(deposit.error)}${notice(deposit.notice)}
        <button class="link-btn" data-commerce-refresh ${deposit.busy ? 'disabled' : ''}>Atualizar disponibilidade</button>`;
    }
    function giftView() {
      const locked = !!(gift.attempt || gift.order || gift.busy);
      const available = gift.catalog.enabled && gift.catalog.items.some(item => item.available);
      const sku = gift.catalog.items.find(item => String(item.id) === gift.selected);
      const preview = gift.preview;
      const order = gift.order;
      let actions = '';
      if (order) {
        const status = order.sandbox && order.status === 'issued'
          ? 'Envio concluído pelo bot. Consulte o canal autorizado.' : REDEMPTION_STATUS[order.status];
        actions += `<div class="commerce-preview" id="wd-status" role="status"><strong>${escape(status)}</strong><p class="form-note">Pedido ${order.id} · ${escape(order.brand)} · ${formatBrl(order.face_value_minor)} · ${count(order.coin_cost)} moedas</p></div>`;
        actions += TERMINAL_REDEMPTION.has(order.status) ? '<button class="ghost" data-giftnew>Preparar outra troca</button>'
          : `<button class="ghost" data-giftcheck ${gift.busy || !giftPoll.getStats().canCheck ? 'disabled' : ''}>Consultar status da troca</button>`;
      } else if (gift.attempt) {
        actions += notice('Confira o resultado da solicitação anterior antes de trocar mais moedas.');
        actions += gift.attempt.orderId
          ? `<button class="ghost" data-giftcheck ${gift.busy || !giftPoll.getStats().canCheck ? 'disabled' : ''}>Consultar status da troca</button>`
          : `<button class="cta" data-giftconfirm ${gift.busy ? 'disabled' : ''}>${gift.busy ? 'Confirmando…' : 'Repetir a mesma solicitação'}</button>`;
      } else if (preview) {
        actions += `<div class="commerce-preview" id="gift-confirmation"><h3>Confirmar a troca</h3><p>1 ${escape(preview.brand)} · ${formatBrl(preview.face_value_minor)} · ${escape(preview.region)}</p><p>Custo: <strong>${count(preview.coin_cost)} moedas de ouro</strong>.</p><p class="form-note">Um cartão por solicitação. O saldo será atualizado somente pela resposta do servidor.</p></div><button class="cta" data-giftconfirm ${gift.busy ? 'disabled' : ''}>Confirmar troca por ${count(preview.coin_cost)} moedas</button>`;
      }
      return `<div class="card-head"><h2>Trocar moedas por gift card</h2></div>
        <p class="form-note">O código é entregue somente pelo bot confiável no Telegram. Não há saque em dinheiro, PIX ou transferência bancária.</p>
        ${gift.catalog.mode === 'sandbox' ? notice('Catálogo disponível conforme as regras e o estoque do servidor.') : ''}
        <div class="controls"><label for="wd-card">Gift card<select id="wd-card" ${locked || !available ? 'disabled' : ''}>
        ${gift.catalog.items.length ? gift.catalog.items.map(item => `<option value="${item.id}" ${String(item.id) === gift.selected ? 'selected' : ''} ${item.available ? '' : 'disabled'}>${escape(item.brand)} · ${formatBrl(item.face_value_minor)} · ${count(item.coin_cost)} moedas${item.available ? '' : ' · indisponível'}</option>`).join('') : '<option value="">Nenhum gift card disponível</option>'}</select></label></div>
        <div id="wd-preview" class="form-note">${sku ? `Valor do gift card: <strong>${formatBrl(sku.face_value_minor)}</strong> · custo: <strong>${count(sku.coin_cost)} moedas</strong> · região: ${escape(sku.region)}` : 'Nenhuma moeda foi gasta.'}</div>
        ${!locked ? `<button class="cta" data-giftpreview ${!available || !sku?.available || openReviewOrders() ? 'disabled' : ''}>Revisar troca</button>` : ''}
        ${!locked && openReviewOrders() ? notice('Há uma troca em andamento. Abra o pedido abaixo antes de solicitar outro gift card.') : ''}
        ${!gift.loaded ? notice('Consultando catálogo…') : !available ? notice('Nenhum gift card disponível. Nenhuma moeda será gasta.') : ''}
        ${actions}${message(gift.error)}${notice(gift.notice)}
        <h3>Minhas trocas</h3>${gift.orders.length ? `<ul class="list">${gift.orders.slice(0, 10).map(item => `<li><span><b>${escape(item.brand)} · ${formatBrl(item.face_value_minor)} · ${count(item.coin_cost)} moedas</b><small>${escape(REDEMPTION_STATUS[item.status])}</small></span><button class="link-btn" data-redemption="${item.id}" ${gift.busy || gift.attempt || order && !TERMINAL_REDEMPTION.has(order.status) ? 'disabled' : ''}>Ver pedido ${item.id}</button></li>`).join('')}</ul>` : '<p class="form-note">Nenhuma troca carregada.</p>'}
        ${message(gift.listError)}${mainBotLink()}<button class="link-btn" data-commerce-refresh ${gift.busy ? 'disabled' : ''}>Atualizar catálogo e pedidos</button>`;
    }
    function botsView() {
      const statuses = { active: 'Ativo', pending: 'Aguardando configuração', pending_setup: 'Aguardando configuração',
        revoked: 'Acesso revogado', disabled: 'Desativado', untrusted: 'Não validado', failed: 'Falha na configuração', setup_failed: 'Falha na configuração' };
      return `<h2>Meu bot pessoal</h2><p class="form-note">Gerencie seu bot pelo bot principal. Nunca envie tokens ou códigos por esta página.</p>
        ${!bots.loaded ? notice('Consultando seus bots…') : ''}${message(bots.error)}
        ${bots.managed_bots.length ? `<ul class="list">${bots.managed_bots.map(bot => `<li><span><b>@${escape(bot.username)}</b><small>${escape(statuses[bot.status] || 'Indisponível')}</small></span></li>`).join('')}</ul>` : bots.loaded && !bots.error ? '<p class="form-note">Nenhum bot pessoal vinculado a esta conta.</p>' : ''}
        ${bots.enabled && bots.create_url ? `<a class="cta" id="create-personal-bot" href="${escape(bots.create_url)}" target="_blank" rel="noopener noreferrer">Criar meu bot pessoal</a>` : '<button class="cta" disabled>Criação de bot indisponível</button>'}
        <p class="form-note">No bot principal: /start managed para criar; /mybot para consultar seu bot.</p>${mainBotLink()}`;
    }

    function handleClick(dataset) {
      const actions = { depquote: previewDeposit, depconfirm: confirmDeposit, depsandbox: settleSandbox,
        depinvoice: prepareInvoice, depopeninvoice: openInvoice, depcheck: () => depositPoll.check(), depnew: newDeposit,
        giftpreview: previewGift, giftconfirm: confirmGift, giftcheck: () => giftPoll.check(), giftnew: newGift,
        commerceRefresh: () => load(true) };
      if (dataset.dep !== undefined) { setAmount(dataset.dep); return true; }
      if (dataset.depmethod !== undefined) { setMethod(dataset.depmethod); return true; }
      if (dataset.redemption !== undefined) { void inspectOrder(dataset.redemption); return true; }
      for (const [key, action] of Object.entries(actions)) if (dataset[key] !== undefined) { void action(); return true; }
      return false;
    }
    function allowPaymentLink() {
      if (!deposit.intent || TERMINAL_DEPOSIT.has(deposit.intent.status) || depositIsExpired()) {
        deposit.error = expireNotice; notify('deposit'); return false;
      }
      try { ensureContext(); return true; }
      catch (error) { deposit.error = errorMessage(error); notify('deposit'); return false; }
    }
    return { load, depositView, giftView, botsView, mainBotLink, handleClick, setAmount, setMethod, setSku, allowPaymentLink,
      previewDeposit, confirmDeposit, settleSandbox, prepareInvoice, openInvoice, previewGift, confirmGift, inspectOrder,
      checkDeposit: () => depositPoll.check(), checkGift: () => giftPoll.check(), newDeposit, newGift,
      visibilityChanged() {
        if (visible()) {
          if (depositIsExpired() && !deposit.attempt && !deposit.intent) { clearQuote(); deposit.error = errorMessage(new ApiError('quote_expired')); }
          notify('deposit'); depositPoll.resume(); giftPoll.resume();
        } else { depositPoll.suspend(); giftPoll.suspend(); }
      },
      dispose() { depositPoll.stop(); giftPoll.stop(); if (quoteTimer !== null) clearTimer(quoteTimer); },
      getState: () => ({ deposit, gift, bots }),
    };
  }

  return { createCommerce, createPoller, formatBrl, formatAtomic, normalizeMethods, normalizeQuote,
    normalizeIntent, normalizeCatalog, normalizeRedemption, safePaymentUrl, safeBotLink, safeReferralLink, navigationTarget };
});
