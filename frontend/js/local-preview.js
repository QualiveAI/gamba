/* Локальный preview без Telegram, backend, БД и платёжных запросов. */
(function (root, factory) {
  const catalog = root.WindropLocalPreviewCatalog || (typeof require === 'function' ? require('./local-preview-catalog.js') : []);
  const preview = factory(root.WindropApi, catalog);
  if (typeof module === 'object' && module.exports) module.exports = preview;
  else root.WindropLocalPreview = preview;
})(globalThis, function (api, catalog) {
  'use strict';

  const ApiError = api && api.ApiError ? api.ApiError : class extends Error {
    constructor(code, status = 0) { super(code); this.code = code; this.status = status; }
  };
  const LOOPBACK = new Set(['localhost', '127.0.0.1', '::1']);
  const PREVIEW_PATHS = new Set(['/preview.html', '/preview']);
  const PREVIEW_TIME = '2030-01-01T00:00:00.000Z';
  const PREVIEW_CONTEXT = 'local-preview:account:preview';
  const CUPS_BY_LEVEL = Object.freeze({ 1: 3, 2: 3, 3: 4, 4: 4, 5: 5, 6: 5 });
  const SHELL_RTP = 0.90;
  const clone = value => JSON.parse(JSON.stringify(value));
  const bodyOf = options => {
    if (!options || typeof options.body !== 'string') return {};
    try { return JSON.parse(options.body) || {}; } catch (_) { return {}; }
  };
  const methodOf = options => String(options && options.method || 'GET').toUpperCase();
  const error = (code, status = 400) => { throw new ApiError(code, status); };
  const shellMult = cups => Math.floor(SHELL_RTP * cups * 100 + 1e-6) / 100;
  // Deterministic synthetic RNG: preview никогда не зависит от live-исходов или ставки игрока.
  const previewRoll = seed => {
    let t = (Math.imul(seed >>> 0, 0x6d2b79f5) + 0x6d2b79f5) >>> 0;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const crashPointFor = round => {
    const roll = previewRoll(round * 7919 + 13);
    const value = Math.round((0.97 / Math.max(0.000001, 1 - roll)) * 100) / 100;
    // Preview-only bounds: без мгновенного x1.00 и без раундов длиннее ~15 секунд.
    return Math.min(6, Math.max(1.2, value));
  };
  const minesFor = (mineCount, round) => {
    const pool = Array.from({ length: 24 }, (_, index) => index + 1);
    let seed = (round * 104729 + mineCount * 31 + 7) >>> 0;
    for (let i = pool.length - 1; i > 0; i--) {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      const j = seed % (i + 1);
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    return pool.slice(0, Math.min(mineCount, pool.length)).sort((a, b) => a - b);
  };
  const CASES = Array.isArray(catalog) ? catalog : [];
  if (CASES.length !== 14 || CASES.some(row => !row || row.rewards?.length !== 15)) {
    throw new Error('Local preview catalog is incomplete');
  }

  function isEnabled(location = globalThis.location) {
    return !!location && LOOPBACK.has(String(location.hostname || '').toLowerCase())
      && PREVIEW_PATHS.has(String(location.pathname || ''));
  }

  function createState() {
    const firstCase = CASES.find(row => row.key === 'adopt') || CASES[0];
    const firstReward = firstCase.rewards[0];
    return {
      gold: 5000,
      copper: 1200,
      inventory: [{ id: 9001, label: firstReward.label, value_coins: firstReward.nominal_units,
        rarity: firstReward.rarity, currency: 'units', image: firstReward.image }],
      history: [{ kind: 'entry', text: 'Bônus de boas-vindas', delta: 5000, currency: 'units', t: PREVIEW_TIME }],
      daily: { can_claim: true, streak: 3, claimed_dates: [] },
      sessions: new Map(),
      nextItemId: 9002,
      nextSessionId: 100,
      opened: 0,
      shellRounds: 0,
      upgradeRounds: 0,
      crashRounds: 0,
      minesRounds: 0,
    };
  }

  function methodsDisabled() {
    return {
      mode: 'disabled',
      methods: [
        ['stars', 'stars', 'Telegram Stars'], ['gift', 'gift', 'Presente Telegram'],
        ['card', 'paygate', 'Cartão'], ['crypto', 'paymento', 'Criptomoedas'],
      ].map(([method, rail, label]) => ({ method, rail, label, mode: 'disabled', enabled: false,
        reason: 'Pagamentos desativados no preview local.' })),
    };
  }

  function createClient({ location = globalThis.location } = {}) {
    if (!isEnabled(location)) throw new Error('Local preview is available only at loopback /preview.html');
    const state = createState();
    let authenticated = false;

    function wallet() { return { units_minor: state.gold, freebets_units: state.copper }; }
    function history(text, delta, currency = 'units') {
      state.history.unshift({ kind: 'entry', text, delta, currency, t: PREVIEW_TIME });
    }
    function findCase(id) { return CASES.find(row => String(row.id) === String(id)); }
    function findSession(id) { return state.sessions.get(Number(id)); }
    function gameSession(type, data) {
      const id = state.nextSessionId++;
      state.sessions.set(id, { id, type, ...data });
      return id;
    }
    function addInventory(row, currency = 'units') {
      const item = { id: state.nextItemId++, label: row.label, value_coins: row.nominal_units,
        rarity: row.rarity, currency, image: row.image };
      state.inventory.unshift(item);
      return item;
    }

    async function request(path, options = {}) {
      if (!authenticated) await authenticate();
      if (typeof path !== 'string' || !/^\/(?!\/)/.test(path)) error('invalid_request');
      const [pathname, query = ''] = path.split('?');
      const method = methodOf(options);
      const body = bodyOf(options);

      if (pathname === '/wallet' && method === 'GET') return clone(wallet());
      if (pathname === '/wallet/history' && method === 'GET') return clone(state.history);
      if (pathname === '/meta/tenant' && method === 'GET') {
        return { tenant: 'local-preview', brand: { name: 'WINDROP', logo_url: '', primary_color: '#c8102e' }, domains: {}, geos: ['BR'], games: ['roblox'] };
      }
      if (pathname === '/meta/payment-methods' && method === 'GET') return methodsDisabled();
      if (pathname === '/giftcards/catalog' && method === 'GET') return { enabled: false, mode: 'disabled', items: [] };
      if (pathname === '/redemptions' && method === 'GET') return [];
      if (pathname === '/bots/me' && method === 'GET') return { enabled: false, main_bot_username: '', managed_bots: [], create_url: null };
      if (pathname === '/referrals/my' && method === 'GET') return { link: '', invited: 0, confirmed: 0 };
      if (pathname === '/rewards/daily/status' && method === 'GET') return clone(state.daily);
      if (pathname === '/rewards/daily/claim' && method === 'POST') {
        if (!state.daily.can_claim) error('request_rejected');
        state.daily = { can_claim: false, streak: state.daily.streak + 1, claimed_dates: ['2030-01-01'] };
        state.copper += 500;
        history('daily_bonus', 500, 'freebets');
        return { amount: 500, streak: state.daily.streak };
      }
      if (pathname === '/cases' && method === 'GET') return clone(CASES);
      const openMatch = pathname.match(/^\/cases\/(\d+)\/open$/);
      if (openMatch && method === 'POST') {
        const itemCase = findCase(openMatch[1]);
        if (!itemCase) error('not_found', 404);
        const balance = itemCase.currency === 'freebets' ? state.copper : state.gold;
        if (balance < itemCase.price_units) error('insufficient_balance', 400);
        if (itemCase.currency === 'freebets') state.copper -= itemCase.price_units;
        else state.gold -= itemCase.price_units;
        const item = itemCase.rewards[state.opened++ % itemCase.rewards.length];
        addInventory(item, itemCase.currency);
        history('case_open', -itemCase.price_units, itemCase.currency);
        return { id: itemCase.id, item: item.label, rarity: item.rarity, image: item.image,
          nominal_units: item.nominal_units, chance_pct: item.chance_pct, credit_units: item.nominal_units };
      }
      if (pathname === '/inventory' && method === 'GET') return clone(state.inventory);
      const sellMatch = pathname.match(/^\/inventory\/(\d+)\/sell$/);
      if (sellMatch && method === 'POST') {
        const index = state.inventory.findIndex(item => item.id === Number(sellMatch[1]));
        if (index < 0) error('not_found', 404);
        const [item] = state.inventory.splice(index, 1);
        if (item.currency === 'freebets') state.copper += item.value_coins;
        else state.gold += item.value_coins;
        history('item_sold', item.value_coins, item.currency);
        return { sold: true, value: item.value_coins, currency: item.currency };
      }
      const upgradeMatch = pathname.match(/^\/inventory\/(\d+)\/upgrade$/);
      if (upgradeMatch && method === 'POST') {
        const item = state.inventory.find(row => row.id === Number(upgradeMatch[1]));
        if (!item || item.currency !== 'units') error('not_found', 404);
        if (!body.target_label || !Number.isSafeInteger(body.target_value) || body.target_value <= item.value_coins
          || typeof body.target_rarity !== 'string' || typeof body.target_image !== 'string') error('invalid_request');
        const chance = Math.min(0.8, Math.max(0.01, item.value_coins / body.target_value * 0.8));
        const roll = state.upgradeRounds++ % 2 === 0 ? 0 : 0.99;
        const success = roll < chance;
        if (success) {
          item.label = String(body.target_label).slice(0, 100);
          item.value_coins = body.target_value;
          item.rarity = String(body.target_rarity).slice(0, 30);
          item.image = body.target_image;
        } else {
          state.inventory = state.inventory.filter(row => row.id !== item.id);
        }
        return { success, chance, roll, value: success ? item.value_coins : 0 };
      }
      if (pathname === '/games/mines/start' && method === 'POST') {
        const stake = Number(body.bet), mineCount = Number(body.mine_count);
        if (!Number.isSafeInteger(stake) || stake <= 0 || state.gold < stake) error('insufficient_balance');
        if (![3, 5, 10].includes(mineCount)) error('invalid_request');
        state.gold -= stake;
        const mines = minesFor(mineCount, state.minesRounds++);
        const sessionId = gameSession('mines', { stake, mineCount, mines, open: [], settled: false });
        return { session_id: sessionId, grid_size: 25, mine_count: mineCount };
      }
      if (pathname === '/games/mines/reveal' && method === 'POST') {
        const session = findSession(body.session_id);
        if (!session || session.type !== 'mines' || session.settled) error('not_found', 404);
        const cell = Number(body.cell);
        if (!Number.isInteger(cell) || cell < 0 || cell > 24 || session.open.includes(cell)) error('invalid_request');
        if (session.mines.includes(cell)) {
          session.settled = true;
          return { hit_mine: true, mines: session.mines, revealed: session.open };
        }
        session.open.push(cell);
        return { hit_mine: false, revealed: [cell], bias_applied: false };
      }
      if (pathname === '/games/mines/cashout' && method === 'POST') {
        const session = findSession(new URLSearchParams(query).get('session_id'));
        if (!session || session.type !== 'mines' || session.settled || !session.open.length) error('not_found', 404);
        session.settled = true;
        const payout = Math.floor(session.stake * (1 + session.open.length * 0.3));
        state.gold += payout;
        history('mines_cashout', payout);
        return { payout, revealed: session.open.length };
      }
      if (pathname === '/games/shell/start' && method === 'POST') {
        const level = Number(body.level);
        const cups = CUPS_BY_LEVEL[level];
        const stake = Number(body.bet);
        if (!cups || !Number.isSafeInteger(level) || !Number.isSafeInteger(stake) || stake <= 0 || state.gold < stake) error('invalid_request');
        state.gold -= stake;
        const ball = state.shellRounds++ % cups;
        const multiplier = shellMult(cups);
        const sessionId = gameSession('shell', { stake, level, cups, ball, multiplier, settled: false });
        return { session_id: sessionId, cups, ball, mult: multiplier };
      }
      if (pathname === '/games/shell/pick' && method === 'POST') {
        const session = findSession(body.session_id);
        if (!session || session.type !== 'shell' || session.settled) error('not_found', 404);
        const guess = Number(body.guess);
        if (!Number.isInteger(guess) || guess < 0 || guess >= session.cups) error('invalid_request');
        session.settled = true;
        const win = guess === session.ball;
        const payout = win ? Math.floor(session.stake * session.multiplier) : 0;
        if (win) {
          state.gold += payout;
          history('shell_win', payout);
        }
        return { win, ball: session.ball, guess, mult: session.multiplier, payout };
      }
      if (pathname === '/games/crash/start' && method === 'POST') {
        const stake = Number(body.bet);
        if (!Number.isSafeInteger(stake) || stake <= 0 || state.gold < stake) error('insufficient_balance');
        state.gold -= stake;
        const started = Date.now();
        const crash = crashPointFor(state.crashRounds++);
        const sessionId = gameSession('crash', { stake, crash, started, status: 'active', result: null });
        return { session_id: sessionId, crash_point: crash, t0_ms: started, growth: 0.12 };
      }
      if (pathname === '/games/crash/status' && method === 'GET') {
        const session = findSession(new URLSearchParams(query).get('session_id'));
        if (!session || session.type !== 'crash') error('not_found', 404);
        const now = Date.now();
        const elapsed = Math.max(0, (now - session.started) / 1000);
        const multiplier = Math.floor(Math.exp(0.12 * elapsed) * 100) / 100;
        if (session.status === 'active' && multiplier >= session.crash) {
          session.status = 'busted';
          session.result = { win: false, m: session.crash, crash: session.crash, payout: 0, session_id: session.id, status: 'busted' };
        }
        return { ...(session.result || { status: session.status, win: false, m: multiplier, crash: session.crash, payout: 0, session_id: session.id }),
          status: session.status, started_at_ms: session.started, server_now_ms: now };
      }
      if (pathname === '/games/crash/cash' && method === 'POST') {
        const session = findSession(new URLSearchParams(query).get('session_id'));
        if (!session || session.type !== 'crash') error('not_found', 404);
        if (session.status !== 'active') return clone(session.result);
        const now = Date.now();
        const elapsed = Math.max(0, (now - session.started) / 1000);
        const multiplier = Math.floor(Math.exp(0.12 * elapsed) * 100) / 100;
        if (multiplier >= session.crash) {
          session.status = 'busted';
          session.result = { win: false, m: session.crash, crash: session.crash, payout: 0, session_id: session.id, status: 'busted' };
          return clone(session.result);
        }
        const payout = Math.floor(session.stake * multiplier);
        session.status = 'cashed';
        session.result = { win: true, m: multiplier, crash: session.crash, payout, session_id: session.id, status: 'cashed' };
        state.gold += payout;
        history('crash_cashout', payout);
        return clone(session.result);
      }
      error('service_unavailable', 503);
    }

    async function authenticate() { authenticated = true; return 'local-preview'; }
    return { request, authenticate, retryAuthentication: authenticate,
      getContext: () => PREVIEW_CONTEXT, getChannel: () => 'web' };
  }

  return Object.freeze({ isEnabled, createClient, PREVIEW_PATH: '/preview.html', CUPS_BY_LEVEL });
});
