/* WINDROP mini-app: существующие игры/каталог и безопасные формы профиля. */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = n => Math.round(n).toLocaleString('pt-BR');
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

const TIERS = {
  common: { name: 'Comum', color: '#c39370', soft: '#48352a' },
  normal: { name: 'Normal', color: '#a5e36c', soft: '#304328' },
  epic: { name: 'Épico', color: '#e59af2', soft: '#4a2e54' },
  legend: { name: 'Lenda', color: '#ffda7c', soft: '#514126' },
  hero: { name: 'Herói', color: '#ff8191', soft: '#502832' },
};
const TIER_ORDER = ['common', 'normal', 'epic', 'legend', 'hero'];
const tierRank = id => TIER_ORDER.indexOf(id);
const coin = (c = 'gold') => `<span class="coin ${c === 'copper' ? 'copper' : ''}" aria-hidden="true"></span>`;
const cur = c => c === 'freebets' ? 'cobre' : 'ouro';
const money = (n, c = 'gold') => `${coin(c)}${fmt(n)}`;
const img = (src, alt) => src ? `<img src="${esc(src)}" alt="${esc(alt)}" decoding="async" loading="lazy">` : '<span class="ph"></span>';
document.addEventListener('error', e => { if (e.target.tagName === 'IMG') e.target.classList.add('broken') }, true);

const ICON = {
  cases: '<path d="M3 9h18v11H3zM3 9l2-5h14l2 5M10 13h4"/>',
  games: '<rect x="2" y="7" width="20" height="11" rx="5"/><path d="M7 11v4M5 13h4M15.5 12h.01M18 14h.01"/>',
  upgrade: '<path d="M12 20V5m-6 6 6-6 6 6"/>',
  inventory: '<path d="M5 8h14l-1 12H6zM9 8V6a3 3 0 0 1 6 0v2"/>',
  profile: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  back: '<path d="M20 12H4m6-6-6 6 6 6"/>', copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
  check: '<path d="m5 12 5 5 9-10"/>', bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>', x: '<path d="m6 6 12 12M6 18 18 6"/>',
  cards: '<rect x="2" y="5" width="13" height="9" rx="2"/><rect x="9" y="11" width="13" height="9" rx="2"/>',
};
const icon = k => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;

/* ---------- API (Telegram WebApp -> JWT в памяти) ---------- */
const getTelegram = () => window.Telegram && window.Telegram.WebApp;
try { const tg = getTelegram(); if (tg) { tg.ready(); tg.expand(); } } catch (_) {}
let sessionStore;
try { sessionStore = window.sessionStorage; } catch (_) {}
const apiClient = WindropApi.createClient({ origin: window.location.origin, search: window.location.search,
  getTelegram, storage: sessionStore });
const api = (path, options) => apiClient.request(path, options);
const commerce = WindropCommerce.createCommerce({ client: apiClient, storage: sessionStore, getTelegram,
  onChange: updateCommerceSection, onWalletChange: async () => {
    await refreshWallet();
    updateProfileBalance();
  } });
let initialState = 'loading', initialError = '', initialAuthError = false, initialPromise = null;
let profileRefreshPromise = null, profileLastRefresh = -Infinity;

/* ---------- state ---------- */
const S = { gold: 0, copper: 0 };
let INV = [], HIST = [], DAILY = { can_claim: true, streak: 0, claimed_dates: [] }, REFS = { link: '', invited: 0, confirmed: 0 };
let CATALOG = [];
const CASE = id => CATALOG.find(c => String(c.id) === String(id));
const LSKEY = 'windrop-prefs-v1';
let L = { thLv: 0, thStreak: 0, rhist: [], stake: 50, mineCount: 3, auto: 0 };
try { L = { ...L, ...(JSON.parse(localStorage.getItem(LSKEY)) || {}) }; } catch (e) {}
const savePrefs = () => { try { localStorage.setItem(LSKEY, JSON.stringify(L)) } catch (e) {} };

function setBal(g, p) {
  const old = { g: S.gold, p: S.copper };
  S.gold = g; S.copper = p;
  renderBal(old.g, old.p);
}
function renderBal(pg, pp) {
  const el = $('#bg'), ec = $('#bc');
  cancelAnimationFrame(renderBal.raf);
  ec.innerHTML = money(S.copper, 'copper');
  if (initialState !== 'ready' || document.hidden || pg === undefined || pg === S.gold || reduced) {
    el.innerHTML = money(S.gold, 'gold'); el.classList.remove('up', 'down'); return;
  }
  const t0 = performance.now();
  el.classList.remove('up', 'down'); el.classList.add(S.gold > pg ? 'up' : 'down');
  const st = t => {
    const k = Math.min(1, (t - t0) / 650), v = Math.round(pg + (S.gold - pg) * (1 - Math.pow(1 - k, 3)));
    el.innerHTML = money(v, 'gold');
    if (k < 1) renderBal.raf = requestAnimationFrame(st);
    else { el.innerHTML = money(S.gold, 'gold'); el.classList.remove('up', 'down') }
  };
  renderBal.raf = requestAnimationFrame(st);
}
function toast(t) {
  const el = $('#toast'); el.textContent = t; el.classList.add('show');
  clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove('show'), 2200);
}
function modal(html) {
  const m = $('#modal');
  m.innerHTML = `<div class="sheet" role="dialog" aria-modal="true"><button class="x" data-close aria-label="Fechar">${icon('x')}</button>${html}</div>`;
  m.hidden = false;
}
function closeModal() { $('#modal').hidden = true; $('#modal').innerHTML = ''; render(); }

/* ---------- fx ---------- */
const pickOne = a => a[Math.floor(Math.random() * a.length)];
const rint = n => { const a = new Uint32Array(1); crypto.getRandomValues(a); return a[0] % n };
const JOKES = {
  minesLose: ['O mineiro erra uma vez só 💥', 'Os diamantes estavam tão perto…', 'Não era a célula certa', 'Bum. Mas ficou bonito', 'A mina manda um oi 👋'],
  minesWin: ['Saiu na hora certa — respeito 🫡', 'Ganância vencida 🧠', 'Mineiro de sangue frio', 'Diamantes no bolso 💎', 'Cabeça fria, saldo quente'],
  thWin: ['Olho de águia 👀', 'O copista entrou em choque', 'A mão é mais rápida que o olho? Hoje não', 'Vigilou como um falcão 🦅', 'Não te enganam'],
  thLose: ['A mão é mais rápida que o olho 🫳', 'A bolinha foi pra praia', 'Era o outro copo', 'Quase! Quase não conta', 'A bolinha mudou de endereço'],
  rkWin: ['Pouso suave 🪂', 'Astronauta do ano 👨‍🚀', 'Saiu da nave em movimento', 'Houston, tudo sob controle', 'A ejeção funcionou'],
  rkLose: ['Houston, temos um problema 💥', 'O foguete foi sem você', 'Quem voa assim?', 'O céu não estava pronto', 'O motor decidiu outro rumo'],
};
const TIPS = ['O foguete não lê pensamentos. Nem os seus', 'Em Minas os diamantes gostam de ficar perto das minas. Ou não', 'Os Copos aceleram a cada vitória — é proibido piscar', 'Série de vitórias nos Copos = mais copos e mais ix', 'O Ouro vem do depósito, dos jogos e dos itens'];
const FIRE = ['#ffcf5a', '#ff7a45', '#ff3d5a', '#fff1b8'], PARTY = ['#ffcf5a', '#ff3d5a', '#58d68d', '#e59af2', '#7ad7ff', '#ff7a45'];
const fx = {
  layer() { let l = $('#fx'); if (!l) { l = document.createElement('div'); l.id = 'fx'; document.body.appendChild(l) } return l },
  center(el) { const r = (el || document.body).getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 } },
  confetti(el, n = 48, cols = PARTY) {
    if (reduced || !el) return; const { x, y } = fx.center(el), L2 = fx.layer();
    for (let i = 0; i < n; i++) {
      const s = document.createElement('i'); s.className = 'conf' + (i % 3 ? '' : ' round');
      s.style.background = pickOne(cols); s.style.left = x + 'px'; s.style.top = y + 'px'; L2.appendChild(s);
      const a = Math.random() * Math.PI * 2, v = 90 + Math.random() * 200, r = Math.random() * 1080 - 540;
      s.animate([{ transform: 'translate(-50%,-50%) rotate(0)', opacity: 1 }, { transform: `translate(${Math.cos(a) * v}px,${Math.sin(a) * v - 90}px) rotate(${r / 2}deg)`, opacity: 1, offset: .45 }, { transform: `translate(${Math.cos(a) * v * 1.25}px,${Math.sin(a) * v + 240}px) rotate(${r}deg)`, opacity: 0 }], { duration: 1200 + Math.random() * 700, easing: 'cubic-bezier(.2,.7,.4,1)' }).onfinish = () => s.remove();
    }
  },
  coins(el, n = 10) {
    if (reduced || !el) return; const a = fx.center(el), t = $('#bg'); if (!t) return;
    const b = fx.center(t), L2 = fx.layer();
    for (let i = 0; i < n; i++) {
      const c = document.createElement('i'); c.className = 'flycoin'; c.style.left = a.x + 'px'; c.style.top = a.y + 'px'; L2.appendChild(c);
      const dx = b.x - a.x, dy = b.y - a.y, jx = (Math.random() - .5) * 140, jy = (Math.random() - .5) * 90;
      c.animate([{ transform: 'translate(-50%,-50%) scale(.4)', opacity: 0 }, { transform: `translate(calc(-50% + ${jx}px),calc(-50% + ${jy}px)) scale(1.15)`, opacity: 1, offset: .3 }, { transform: `translate(calc(-50% + ${dx}px),calc(-50% + ${dy}px)) scale(.45)`, opacity: .9 }], { duration: 650 + i * 55, easing: 'cubic-bezier(.5,0,.7,1)' }).onfinish = () => { c.remove(); t.classList.remove('bump'); void t.offsetWidth; t.classList.add('bump') };
    }
  },
  float(el, text, cls = '') {
    if (!el) return; const { x, y } = fx.center(el), f = document.createElement('b');
    f.className = 'floater ' + cls; f.textContent = text; f.style.left = x + 'px'; f.style.top = y + 'px';
    fx.layer().appendChild(f); setTimeout(() => f.remove(), 1300);
  },
  shake(el) { el = el || $('#view'); if (reduced || !el) return; el.classList.remove('shake2'); void el.offsetWidth; el.classList.add('shake2'); setTimeout(() => el.classList.remove('shake2'), 520) },
  flash(c = 'red') { if (reduced) return; const f = document.createElement('i'); f.className = 'flash ' + c; fx.layer().appendChild(f); setTimeout(() => f.remove(), 650) },
  big(x) {
    if (x < 5) return; const d = document.createElement('div'); d.className = 'bigwin';
    d.innerHTML = `<span>${x >= 20 ? 'MEGA VITÓRIA' : 'GRANDE VITÓRIA'}</span><b>x${x.toFixed(2)}</b>`;
    fx.layer().appendChild(d); fx.confetti(d, 100); setTimeout(() => d.remove(), 2300);
  },
  win(el, w, x) { fx.float(el, '+' + fmt(w), 'good'); fx.coins(el, Math.min(18, 6 + Math.floor(x * 2))); fx.confetti(el, x >= 3 ? 70 : 40); fx.flash('green'); fx.big(x) },
  lose(el) { fx.shake(el); fx.flash('red') },
};

/* ---------- загрузка данных ---------- */
async function loadCatalog() {
  const rows = await api('/cases');
  CATALOG = rows.map(c => ({
    id: c.id, name: c.name, price: c.price_units, currency: c.currency || 'units',
    cover: c.cover,
    rewards: (c.rewards || []).map((r, index) => ({
      rid: r.id, name: r.label || 'Item', tier: r.rarity && TIERS[r.rarity] ? r.rarity : 'common',
      chance: r.chance_pct ?? 0, value: r.nominal_units, image: r.image, caseId: c.id,
      caseCurrency: c.currency || 'units', _order: index,
    })).sort((a, b) => tierRank(b.tier) - tierRank(a.tier) || b.value - a.value || a._order - b._order),
  }));
}
let walletRequestVersion = 0;
async function refreshWallet() {
  const version = ++walletRequestVersion;
  const d = await api('/wallet');
  if (version === walletRequestVersion) { setBal(d.units_minor ?? d.units ?? 0, d.freebets_units ?? d.freebets ?? 0); updateProfileBalance(); }
}
async function refreshInv() { INV = await api('/inventory'); }
async function refreshHist() { try { HIST = await api('/wallet/history') } catch (e) { HIST = [] } }
async function refreshDaily() { try { DAILY = await api('/rewards/daily/status') } catch (e) {} }
async function refreshRefs() {
  try {
    const data = await api('/referrals/my');
    const safeCount = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
    REFS = { link: WindropCommerce.safeReferralLink(data?.link) || '',
      invited: safeCount(data?.invited), confirmed: safeCount(data?.confirmed) };
  } catch (_) {
    // Ошибка сервера делает ранее полученную ссылку недоступной, а не оставляет старый CTA.
    REFS = { link: '', invited: 0, confirmed: 0 };
  }
}
async function applyBrand() {
  try {
    const t = await api('/meta/tenant');
    if (t.brand && t.brand.name) { document.title = t.brand.name; $('#brand-name').textContent = t.brand.name }
    if (t.brand && t.brand.primary_color) document.documentElement.style.setProperty('--accent', t.brand.primary_color);
  } catch (e) {}
}

/* ---------- routing ---------- */
let tab = 'cases', sub = null, cat = 'gold';
let profileTarget = WindropCommerce.navigationTarget(window.location.hash, getTelegram()?.initDataUnsafe?.start_param);
if (profileTarget) tab = 'profile';
function go(t, s = null) {
  leaveStakeGames(); stopGames(); tab = t; sub = s;
  render();
  const v = $('#view'); v.classList.remove('enter'); void v.offsetWidth; v.classList.add('enter'); window.scrollTo(0, 0);
  if (tab === 'profile' && initialState === 'ready') { void refreshProfile(); scrollProfileTarget(); }
}
function render() {
  $$('.nav button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  const v = $('#view');
  if (initialState !== 'ready') {
    v.innerHTML = initialState === 'loading' ? '<section class="card" role="status"><h1 class="title">Carregando…</h1><p class="form-note">Validando a sessão do Telegram e consultando o servidor.</p></section>'
      : `<section class="card" role="alert"><h1 class="title">${initialAuthError ? 'Abrir pelo Telegram' : 'Serviço indisponível'}</h1><p class="form-error">${esc(initialError)}</p><p class="form-note">${initialAuthError ? 'Use /start no bot principal e toque no botão da Mini App. Se o link pessoal não funcionar, abra novamente pelo bot principal. Nenhuma conta de visitante será criada.' : 'Não foi possível carregar seus dados. O catálogo não foi substituído por dados temporários.'}</p><button class="cta" data-initretry>Tentar novamente</button></section>`;
    return;
  }
  v.innerHTML = tab === 'cases' ? (sub ? vCase(sub) : vCases())
    : tab === 'games' ? (sub ? vGame(sub) : vGames())
    : tab === 'upgrade' ? vUpgrade()
    : tab === 'inventory' ? vInventory()
    : vProfile();
  if (tab === 'profile') { void commerce.load(); void refreshProfile(); }
}
function scrollProfileTarget() {
  if (tab !== 'profile' || !profileTarget || initialState !== 'ready') return;
  const target = document.getElementById(profileTarget);
  if (target) { target.scrollIntoView({ block: 'start' }); profileTarget = null; }
}
window.addEventListener('hashchange', () => {
  const target = WindropCommerce.navigationTarget(window.location.hash, null);
  if (target) { profileTarget = target; go('profile'); }
});
function updateCommerceSection(section) {
  if (tab !== 'profile' || initialState !== 'ready') return;
  const views = { deposit: ['deposit', () => commerce.depositView()], gift: ['withdraw', () => commerce.giftView()], bots: ['personal-bot', () => commerce.botsView()] };
  const entry = views[section];
  const el = entry && document.getElementById(entry[0]);
  if (!el) return;
  const focused = el.contains(document.activeElement) ? document.activeElement.id : '';
  el.innerHTML = entry[1]();
  if (focused) document.getElementById(focused)?.focus({ preventScroll: true });
}
function updateProfileBalance() {
  if (tab !== 'profile' || initialState !== 'ready') return;
  const gold = $('#profile-gold'), copper = $('#profile-copper');
  if (gold) gold.textContent = fmt(S.gold);
  if (copper) copper.textContent = fmt(S.copper);
}
async function refreshProfile(force = false) {
  if (profileRefreshPromise) return force ? profileRefreshPromise.then(() => refreshProfile(true)) : profileRefreshPromise;
  if (!force && Date.now() - profileLastRefresh < 30000) return;
  profileRefreshPromise = Promise.all([refreshDaily(), refreshRefs(), refreshHist(), refreshWallet().catch(() => {})]).then(() => {
    // Асинхронный ответ профиля не перерисовывает игру и не затирает введённые суммы/котировку.
    if (tab !== 'profile' || initialState !== 'ready') return;
    updateProfileBalance();
    const fragment = document.createElement('div'); fragment.innerHTML = vProfile();
    for (const id of ['profile-daily', 'profile-referrals', 'profile-history']) {
      const current = document.getElementById(id), updated = fragment.querySelector('#' + id);
      if (current && updated) current.innerHTML = updated.innerHTML;
    }
  }).finally(() => { profileLastRefresh = Date.now(); profileRefreshPromise = null; });
  return profileRefreshPromise;
}

/* ---------- cases ---------- */
function vCases() {
  const list = CATALOG.filter(c => (cat === 'gold' ? 'units' : 'freebets') === c.currency);
  return `<h1 class="title">Caixas</h1>
 <div class="seg" role="tablist">${[['gold', 'Por Ouro'], ['freebet', 'Por Cobre']].map(([k, l]) => `<button role="tab" aria-selected="${cat === k}" data-cat="${k}" class="${cat === k ? 'on' : ''}">${l}</button>`).join('')}</div>
 <div class="cases">${list.map((c, n) => {
    const loot = c.rewards.filter(i => i.image).slice(0, 3);
    return `<button class="case" data-case="${c.id}" style="--i:${n}"><span class="case-no">${String(n + 1).padStart(2, '0')}</span><span class="case-img">${img(c.cover, c.name)}</span><b>${esc(c.name)}</b><span class="price ${c.currency === 'freebets' ? 'copper' : ''}">${money(c.price, c.currency)}</span>${loot.length ? `<span class="case-loot">${loot.map(i => `<img src="${esc(i.image)}" alt="${esc(i.name)}" decoding="async" loading="lazy">`).join('')}</span>` : ''}</button>`;
  }).join('') || '<p class="hint">Nenhuma caixa ainda.</p>'}</div>`;
}
const itemCard = (i, extra = '') => {
  const t = TIERS[i.tier] || TIERS.common;
  return `<div class="item" style="--r:${t.color};--rs:${t.soft}"><div class="item-img">${img(i.image, i.name)}</div><div class="item-body"><span class="tier">${t.name}</span><b>${esc(i.name)}</b><span class="val">${coin()}${fmt(i.value)}</span>${extra}</div></div>`;
};
function vCase(id) {
  const c = CASE(id);
  if (!c) return vCases();
  const can = (c.currency === 'freebets' ? S.copper : S.gold) >= c.price;
  return `<button class="back" data-back>${icon('back')}Caixas</button>
 <section class="hero"><div class="hero-img">${img(c.cover, c.name)}</div><h1>${esc(c.name)}</h1>
 <div class="strip-wrap" hidden><div class="pointer"></div><div class="strip" id="strip"></div></div>
 <button class="cta" data-open="${c.id}" ${can ? '' : 'disabled'}>Abrir por ${money(c.price, c.currency)}</button>
 ${can ? '' : `<p class="hint">Faltam moedas. Ganhe nos jogos ou no check-in diário.</p>`}</section>
 <h2 class="sec">Conteúdo · ${c.rewards.length}</h2>
 <div class="items">${c.rewards.map(i => itemCard(i, `<span class="ch">Chance ${String(i.chance).replace('.', ',')}%</span>`)).join('')}</div>`;
}
let busy = false;
async function openCase(id) {
  if (busy) return;
  const c = CASE(id);
  if (!c) return;
  const bal = c.currency === 'freebets' ? S.copper : S.gold;
  if (bal < c.price) return;
  busy = true;
  const btn = $('[data-open]'); if (btn) btn.disabled = true;
  if (c.currency === 'freebets') setBal(S.gold, S.copper - c.price); else setBal(S.gold - c.price, S.copper);
  let res;
  try {
    res = await api(`/cases/${id}/open`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_seed: crypto.randomUUID() }),
    });
  } catch (e) {
    busy = false; toast('Erro: ' + e.message); refreshWallet(); render(); return;
  }
  const win = {
    name: res.item, tier: res.rarity && TIERS[res.rarity] ? res.rarity : 'common',
    image: res.image, value: res.nominal_units, chance: res.chance_pct,
  };
  // рулетка: 44 ячейки, выигрыш под указателем
  const N = 44, K = N - 6, cells = [];
  for (let k = 0; k < N; k++) cells.push(k === K ? win : pickOne(c.rewards));
  const wrap = $('.strip-wrap'), strip = $('#strip');
  wrap.hidden = false;
  strip.style.transition = 'none'; strip.style.transform = 'translateX(0)';
  strip.innerHTML = cells.map(i => `<div class="cell" style="--r:${(TIERS[i.tier] || TIERS.common).color}">${img(i.image, i.name)}</div>`).join('');
  const cw = 96, shift = K * cw + 44 - wrap.clientWidth / 2 + (Math.random() - .5) * 50;
  const ms = reduced ? 0 : 4200;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    strip.style.transition = ms ? `transform ${ms}ms cubic-bezier(.12,.75,.16,1)` : 'none';
    strip.style.transform = `translateX(${-shift}px)`;
  }));
  setTimeout(async () => {
    busy = false;
    try { await refreshInv(); } catch (e) {}
    const invItem = INV[0] && INV[0].label === win.name ? INV[0] : null;
    winModal(win, invItem);
    refreshWallet();
  }, ms + 250);
}
function winModal(i, invItem) {
  const t = TIERS[i.tier] || TIERS.common;
  const sellBtn = invItem ? `<button class="ghost" data-sell="${invItem.id}">Vender por ${money(i.value)}</button>` : '';
  modal(`<div class="win" style="--r:${t.color};--rs:${t.soft}"><span class="tier">${t.name}</span><div class="win-img">${img(i.image, i.name)}</div><h2>${esc(i.name)}</h2><p class="val">${coin()}${fmt(i.value)} ouro</p>
 <div class="row">${sellBtn}<button class="cta" data-close>Para a Mochila</button></div></div>`);
  setTimeout(() => {
    const e = $('.win-img');
    if (['legend', 'hero'].includes(i.tier)) { fx.confetti(e, 110); fx.flash('gold'); if (i.tier === 'hero') fx.shake($('.sheet')) }
    else if (i.tier === 'epic') fx.confetti(e, 55);
    else if (i.tier === 'normal') fx.confetti(e, 20);
  }, 60);
}
async function sell(id) {
  try {
    const res = await api(`/inventory/${id}/sell`, { method: 'POST' });
    if (res.currency === 'freebets') setBal(S.gold, S.copper + res.value); else setBal(S.gold + res.value, S.copper);
    toast(`+${fmt(res.value)} ${cur(res.currency)}`);
    fx.coins($('.inv-head') || $('#view'), 8);
  } catch (e) { toast('Erro: ' + e.message) }
  await refreshInv();
  if (!$('#modal').hidden) return closeModal();
  render();
}

/* ---------- upgrade ---------- */
let upSel = null, upTarget = null, upBusy = false;
const mine = () => INV.filter(i => i.value_coins > 0).map(i => ({
  id: i.id, name: i.label, tier: i.rarity && TIERS[i.rarity] ? i.rarity : 'common',
  value: i.value_coins, image: i.image, currency: i.currency,
}));
function catalogTargets(sel) {
  const seen = new Set(), out = [];
  for (const c of CATALOG) for (const i of c.rewards) {
    if (i.caseCurrency !== 'units') continue;
    if (i.value <= sel.value) continue;
    const k = i.name + i.value;
    if (seen.has(k)) continue;
    seen.add(k); out.push(i);
  }
  return out.sort((a, b) => a.value - b.value).slice(0, 30);
}
const chanceOf = (a, b) => Math.min(80, Math.max(1, a.value / b.value * 80));
const miniCard = i => `<div class="mini" style="--r:${(TIERS[i.tier] || TIERS.common).color}">${img(i.image, i.name)}<b>${esc(i.name)}</b><span>${coin()}${fmt(i.value)}</span></div>`;
const pickCard = (i, attr, val, on) => `<button class="pick ${on ? 'on' : ''}" ${attr}="${val}" style="--r:${(TIERS[i.tier] || TIERS.common).color}">${img(i.image, i.name)}<b>${esc(i.name)}</b><span>${coin()}${fmt(i.value)}</span></button>`;
function vUpgrade() {
  const list = mine(), sel = list.find(i => i.id === upSel);
  const tgt = sel && upTarget && upTarget.value > sel.value ? upTarget : null;
  const ch = sel && tgt ? chanceOf(sel, tgt) : 0;
  return `<h1 class="title">Aprimorar</h1><p class="sub">Coloque um item da Mochila e tente transformá-lo em um mais caro. Quanto maior a diferença, menor a chance. Se falhar, o item queima.</p>
 <div class="up-stage"><div class="up-slot">${sel ? miniCard(sel) : '<span class="slot-empty">Seu item</span>'}</div>
 <div class="ring" style="--p:${ch}"><div class="ring-in"><b>${ch ? ch.toFixed(1).replace('.', ',') + '%' : '—'}</b><small>chance</small></div><div class="arrow" id="arrow"></div></div>
 <div class="up-slot">${tgt ? miniCard(tgt) : '<span class="slot-empty">Meta</span>'}</div></div>
 <button class="cta" data-upgo ${sel && tgt && !upBusy ? '' : 'disabled'}>Aprimorar</button>
 <h2 class="sec">1. Seu item</h2>
 ${list.length ? `<div class="picks">${list.map(i => pickCard(i, 'data-upsel', i.id, i.id === upSel)).join('')}</div>` : `<div class="empty"><p>A Mochila está vazia. Abra uma caixa para ganhar o primeiro item.</p><button class="ghost" data-tab="cases">Abrir caixa</button></div>`}
 ${sel ? `<h2 class="sec">2. Meta</h2>${(() => { const t = catalogTargets(sel); return t.length ? `<div class="picks">${t.map(i => pickCard(i, 'data-uptgt', i.rid, tgt && tgt.rid === i.rid)).join('')}</div>` : '<div class="empty"><p>Este já é o item mais caro.</p></div>' })()}` : ''}`;
}
async function doUpgrade() {
  const sel = mine().find(i => i.id === upSel), tgt = upTarget;
  if (!sel || !tgt || upBusy) return;
  const ch = chanceOf(sel, tgt);
  upBusy = true; const btn = $('[data-upgo]'); if (btn) btn.disabled = true;
  let res;
  try {
    res = await api(`/inventory/${sel.id}/upgrade`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_value: tgt.value, target_label: tgt.name, target_image: tgt.image, target_rarity: tgt.tier }),
    });
  } catch (e) { upBusy = false; toast('Erro: ' + e.message); render(); return }
  const deg = ch * 3.6, win = res.success;
  const land = win ? deg * (.1 + Math.random() * .8) : deg + (360 - deg) * (.05 + Math.random() * .9);
  const a = $('#arrow'), ms = reduced ? 0 : 3200;
  a.style.transition = ms ? `transform ${ms}ms cubic-bezier(.15,.8,.2,1)` : 'none';
  a.style.transform = `rotate(${1800 + land}deg)`;
  setTimeout(async () => {
    upBusy = false; upSel = null; upTarget = null;
    await refreshInv();
    render();
    modal(win
      ? `<div class="result ok"><div class="badge">${icon('check')}</div><h2>Deu certo!</h2><p>${esc(sel.name)} → <b>${esc(tgt.name)}</b></p><button class="cta" data-close>Beleza</button></div>`
      : `<div class="result bad"><div class="badge">${icon('x')}</div><h2>Azarel</h2><p>${esc(sel.name)} queimou. A chance era ${ch.toFixed(1).replace('.', ',')}%.</p><button class="cta" data-close>Entendi</button></div>`);
    setTimeout(() => { if (win) { fx.confetti($('.result'), 80); fx.flash('green') } else { fx.shake($('.sheet')); fx.flash('red') } }, 60);
  }, ms + 300);
}

/* ---------- inventory ---------- */
function vInventory() {
  const list = mine(), total = list.reduce((s, i) => s + i.value, 0);
  return `<h1 class="title">Mochila</h1>
 <div class="inv-head"><div><small>Itens</small><b>${list.length}</b></div><div><small>Valor total</small><b>${money(total)}</b></div>${list.length ? `<button class="ghost" data-sellall>Vender tudo</button>` : ''}</div>
 ${list.length ? `<div class="items">${list.map(i => itemCard(i, `<div class="item-actions"><button class="mini-btn" data-sell="${i.id}">Vender</button><button class="mini-btn accent" data-toup="${i.id}">Aprimorar</button></div>`)).join('')}</div>` : `<div class="empty"><p>Aqui aparecem os itens das caixas e dos aprimoramentos.</p><button class="ghost" data-tab="cases">Abrir caixa</button></div>`}
 <p class="note">Itens são do jogo: use-os no Aprimorar ou venda por Ouro.</p>`;
}
async function sellAll() {
  const list = mine(), n = list.length;
  if (!n) return;
  toast(`Vendendo ${n} itens…`);
  for (const i of list) { try { await api(`/inventory/${i.id}/sell`, { method: 'POST' }) } catch (e) {} }
  await refreshInv(); await refreshWallet();
  render(); toast(`Vendidos ${n} itens`);
}

/* ---------- games ---------- */
const GAMES = [
  { id: 'minas', name: 'Minas', desc: 'Campo 5×5: abra diamantes, desvie das minas e saque na hora certa.', tag: 'até x6 900 na aposta', art: '<span class="art-ico">💎</span>' },
  { id: 'copos', name: 'Copos', desc: 'Siga a bolinha embaixo dos copos e acerte onde ela parou.', tag: 'x2.90 na aposta', art: '<span class="mini-cups"><i></i><i></i><i></i></span>' },
  { id: 'foguete', name: 'Foguete', desc: 'O multiplicador sobe enquanto o foguete voa. Saque antes de explodir.', tag: 'até x1000 na aposta', art: '<span class="art-ico">🚀</span>' },
];
function vGames() {
  return `<h1 class="title">Mini-jogos</h1><p class="sub">Jogamos com Ouro do saldo real: vem de depósitos, itens vendidos e do check-in diário.</p>
 <p class="joke">💬 ${pickOne(TIPS)}</p><div class="games">${GAMES.map((g, n) => `<button class="game g-${g.id}" data-game="${g.id}"><span class="game-art">${g.art}</span><span class="game-copy"><b>${g.name}</b><span>${g.desc}</span><em>${g.tag}</em></span></button>`).join('')}</div>`;
}
function vGame(id) {
  const head = t => `<button class="back" data-back>${icon('back')}Jogos</button><h1 class="title">${t}</h1>`;
  const SG = { minas: vMines, copos: vCopos, foguete: vFoguete };
  if (SG[id]) return head(GAMES.find(g => g.id === id).name) + SG[id]();
  return vGames();
}
let gameTimers = [];
function stopGames() { gameTimers.forEach(t => { clearInterval(t); clearTimeout(t) }); gameTimers = [] }

/* ставки */
const RTP = .97, COPOS_RTP = .9, STAKES = [10, 50, 100, 250, 500];
const stakeBar = () => `<div class="stake"><small>Aposta</small><div class="stake-row">${STAKES.map(v => `<button class="st${v === L.stake ? ' on' : ''}" data-stake="${v}" ${v > S.gold ? 'disabled' : ''}>${fmt(v)}</button>`).join('')}</div>${S.gold < STAKES[0] ? '<p class="hint">Ouro insuficiente — faça um depósito no Perfil ou pegue o check-in diário</p>' : ''}</div>`;

/* minas */
const MN = 25, MINE_OPTS = [3, 5, 10];
const minesMult = (m, k) => { let x = 1; for (let i = 0; i < k; i++) x *= (MN - i) / (MN - m - i); return Math.floor(x * RTP * 100) / 100 };
let mns = null; // {sid, stake, m, open:[], over, won}
function vMines() {
  const r = mns, live = !!(r && !r.over), m = live ? r.m : L.mineCount, k = live ? r.open.length : 0;
  const now = k ? minesMult(m, k) : 1, next = k < MN - m ? 'x' + minesMult(m, k + 1).toFixed(2) : '—';
  return `<div class="tap-stats"><div><small>Multiplicador</small><b class="${k ? 'pulse' : ''}">x${now.toFixed(2)}</b></div><div><small>Próximo</small><b>${next}</b></div></div>
 ${live ? '' : stakeBar() + `<div class="stake"><small>Minas no campo</small><div class="stake-row">${MINE_OPTS.map(v => `<button class="st${v === L.mineCount ? ' on' : ''}" data-minecount="${v}">${v}</button>`).join('')}</div></div>`}
 <div class="mines-grid">${Array.from({ length: MN }, (_, i) => {
    const op = !!(r && r.open.includes(i)), bm = !!(r && r.over && (r.minesShown || []).includes(i));
    return `<button class="mcell${op ? ' gem' : ''}${bm ? ' mine' : ''}${r && r.over && r.hit === i ? ' hit' : ''}" data-cell="${i}" style="--d:${(i % 5 + Math.floor(i / 5)) * 45}ms" ${!live || op ? 'disabled' : ''} aria-label="Célula ${i + 1}">${op ? '💎' : bm ? '💣' : ''}</button>`;
  }).join('')}</div>
 ${r && r.over ? `<p class="hint">${r.won ? `Sacou ${money(r.won)}` : 'Mina! Aposta queimou'}</p>` : ''}
 ${live ? `<button class="cta wide" data-mcash ${k ? '' : 'disabled'}>Sacar ${money(Math.floor(r.stake * now))}</button>` : `<button class="cta wide" data-mplay>Jogar · ${money(L.stake)}</button>`}
 <p class="rules">Abra células com diamantes. Cada diamante sobe o multiplicador, mina queima a aposta. Saque quando quiser. Retorno ao jogador ${Math.round(RTP * 100)}%.</p>`;
}
async function minesStart() {
  if (S.gold < L.stake) { toast(`Precisa de ${fmt(L.stake)} ouro`); return }
  try {
    const res = await api('/games/mines/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bet: L.stake, mine_count: L.mineCount }),
    });
    mns = { sid: res.session_id, stake: L.stake, m: L.mineCount, open: [], over: false, won: 0, minesShown: null, hit: -1 };
    setBal(S.gold - L.stake, S.copper);
    render();
  } catch (e) { toast('Erro: ' + e.message); refreshWallet() }
}
async function minesOpen(i) {
  const r = mns;
  if (!r || r.over || r.open.includes(i)) return;
  let res;
  try {
    res = await api('/games/mines/reveal', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: r.sid, cell: i }),
    });
  } catch (e) { toast('Erro: ' + e.message); return }
  if (res.hit_mine) {
    r.over = true; r.hit = i; r.minesShown = res.mines || [];
    render(); fx.lose($('.mines-grid')); toast(pickOne(JOKES.minesLose)); refreshWallet();
    return;
  }
  r.open.push(i);
  if (r.open.length === MN - r.m) return minesCash();
  render(); fx.float($(`[data-cell="${i}"]`), 'x' + minesMult(r.m, r.open.length).toFixed(2), 'good');
}
async function minesCash() {
  const r = mns;
  if (!r || r.over || !r.open.length) return;
  let res;
  try { res = await api(`/games/mines/cashout?session_id=${r.sid}`, { method: 'POST' }) }
  catch (e) { toast('Erro: ' + e.message); return }
  const x = minesMult(r.m, r.open.length), w = res.payout ?? Math.floor(r.stake * x);
  r.over = true; r.won = w;
  setBal(S.gold + w, S.copper);
  render(); fx.win($('.mines-grid'), w, x); toast(pickOne(JOKES.minesWin)); refreshWallet();
}

/* copos (напёрстки): уровни как в демо, шарик фиксирует сервер на старте */
const TH_LV = [
  { n: 3, swaps: 6, sp: 430, name: 'Aquecimento' },
  { n: 3, swaps: 10, sp: 320, name: 'Mãos leves' },
  { n: 4, swaps: 13, sp: 260, name: 'Mestre da estação' },
  { n: 4, swaps: 17, sp: 210, name: 'Mágico' },
  { n: 5, swaps: 21, sp: 170, name: 'Olho de águia' },
  { n: 5, swaps: 26, sp: 130, name: 'Lenda dos copos' },
];
const thX = n => Math.floor(COPOS_RTP * n * 100 + 1e-6) / 100;
const thLvIdx = () => Math.min(L.thLv || 0, TH_LV.length - 1);
let thim = { phase: 'idle', ball: 0, pos: [0, 1, 2], pick: null, win: false, stake: 0, n: 3, x: thX(3), lv: 0, sid: 0 };
function vCopos() {
  const p = thim.phase, idle = p === 'idle' || p === 'done', lvi = idle ? thLvIdx() : thim.lv, Lv = TH_LV[lvi];
  const cn = p === 'idle' ? Lv.n : thim.n, pos = p === 'idle' ? [...Array(cn).keys()] : thim.pos, showBall = p === 'show' || p === 'done';
  return `<div class="tap-stats"><div><small>Ganho</small><b>x${thX(Lv.n).toFixed(2)}</b></div><div><small>Chance</small><b>1 de ${Lv.n}</b></div><div><small>Série</small><b>${L.thStreak || 0} 🔥</b></div></div>
 <div class="th-lv"><div class="th-dots">${TH_LV.map((l, k) => `<i class="${k < lvi ? 'done' : k === lvi ? 'on' : ''}"></i>`).join('')}</div><span>Nv. ${lvi + 1} · ${Lv.name} · ${Lv.n} copos, ${Lv.swaps} embaralhadas</span></div>
 ${idle ? stakeBar() : ''}
 <div class="cups${p === 'shuffle' ? ' busy' : ''}" style="--n:${cn};--sp:${thim.sp || Lv.sp}ms">${Array.from({ length: cn }, (_, k) => {
    const up = (p === 'show' && k === thim.ball) || (p === 'done' && (k === thim.pick || k === thim.ball));
    return `<button class="cup${up ? ' up' : ''}${p === 'done' && k === thim.pick ? (thim.win ? ' good' : ' miss') : ''}" data-cup="${k}" style="--s:${pos[k]}" ${p !== 'pick' ? 'disabled' : ''} aria-label="Copo ${k + 1}"><span class="cup-body"></span></button>`;
  }).join('')}
 <span class="ball${showBall ? ' on' : ''}" style="--s:${pos[thim.ball] ?? 0}"></span><span class="table"></span></div>
 <p class="hint">${p === 'idle' ? 'Siga a bolinha e acerte o copo' : p === 'show' ? 'Decore onde está a bolinha 👀' : p === 'shuffle' ? 'Enrolando…' : p === 'pick' ? 'Onde está a bolinha?' : thim.win ? `Acertou! +${fmt(Math.floor(thim.stake * thim.x + 1e-6))} ouro` : 'Errou — a bolinha estava em outro copo'}</p>
 ${idle ? `<button class="cta wide" data-tplay>${p === 'done' ? (thim.win ? 'Continuar · nv. ' + (lvi + 1) : 'De novo') : 'Jogar'} · ${money(L.stake)}</button>` : ''}
 <p class="rules">A cada vitória seguida os copos giram mais rápido e mais vezes, no 3º nível viram 4, no 5º — 5. O ganho cresce com o número de copos. Errou — a série zera, volta ao aquecimento.</p>`;
}
async function coposStart() {
  const lv = thLvIdx(), Lv = TH_LV[lv];
  if (S.gold < L.stake) { toast(`Precisa de ${fmt(L.stake)} ouro`); return }
  let res;
  try {
    res = await api('/games/shell/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bet: L.stake, level: lv + 1, client_seed: crypto.randomUUID() }),
    });
  } catch (e) { toast('Erro: ' + e.message); refreshWallet(); return }
  thim = { phase: 'show', ball: res.ball, pos: [...Array(res.cups).keys()], pick: null, win: false, stake: L.stake, n: res.cups, x: res.mult, lv, sp: Math.round(Lv.sp * 1.3), sid: res.session_id };
  setBal(S.gold - L.stake, S.copper);
  render();
  gameTimers.push(setTimeout(() => {
    if (thim.phase !== 'show') return;
    thim.phase = 'shuffle'; render();
    let left = Lv.swaps, sp = reduced ? Math.min(Lv.sp, 200) : Lv.sp * 1.3;
    const step = () => {
      if (thim.phase !== 'shuffle') return;
      const a = rint(Lv.n); let b = rint(Lv.n - 1); if (b >= a) b++;
      const ia = thim.pos.indexOf(a), ib = thim.pos.indexOf(b);
      thim.pos[ia] = b; thim.pos[ib] = a; thim.sp = Math.round(sp);
      const box = $('.cups'); if (box) box.style.setProperty('--sp', thim.sp + 'ms');
      [[ia, 'fwd'], [ib, 'bwd']].forEach(([k, c]) => {
        const el = $(`[data-cup="${k}"]`);
        if (el) { el.style.setProperty('--s', thim.pos[k]); el.classList.remove('fwd', 'bwd'); void el.offsetWidth; el.classList.add(c) }
      });
      const bl = $('.ball'); if (bl) bl.style.setProperty('--s', thim.pos[thim.ball]);
      sp = Math.max(Lv.sp * .6, sp * .93);
      if (--left <= 0) { gameTimers.push(setTimeout(() => { thim.phase = 'pick'; render() }, sp + 150)); return }
      gameTimers.push(setTimeout(step, sp + 20));
    };
    step();
  }, 1300));
}
async function coposPick(k) {
  if (thim.phase !== 'pick') return;
  thim.phase = 'done'; thim.pick = k;
  let res;
  try {
    res = await api('/games/shell/pick', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: thim.sid, guess: k }),
    });
  } catch (e) { toast('Erro: ' + e.message); thim.phase = 'idle'; render(); return }
  thim.win = !!res.win; thim.ball = res.ball;
  if (thim.win) {
    const w = res.payout ?? Math.floor(thim.stake * thim.x), before = thLvIdx();
    setBal(S.gold + w, S.copper);
    L.thLv = Math.min(TH_LV.length - 1, (L.thLv || 0) + 1); L.thStreak = (L.thStreak || 0) + 1; savePrefs(); render();
    fx.win($(`[data-cup="${k}"]`), w, thim.x);
    const up = thLvIdx() > before;
    toast(pickOne(JOKES.thWin) + (up ? ` · Nível ${thLvIdx() + 1}: ${TH_LV[thLvIdx()].name}` : ''));
  } else {
    L.thLv = 0; L.thStreak = 0; savePrefs(); render();
    fx.lose($('.cups')); toast(pickOne(JOKES.thLose));
  }
  refreshWallet();
}

/* foguete (crash): живой полёт, кэшаут в любой момент, взрыв по точке сервера */
const AUTOS = [0, 1.5, 2, 3, 5];
let rk = { phase: 'idle', m: 1, crash: 1, t0: 0, stake: 0, auto: 0, sid: 0, pp: 0 };
const rkPos = p => `left:${(8 + p * 70).toFixed(2)}%;bottom:${(12 + 52 * Math.pow(p, 1.6)).toFixed(2)}%`;
const heat = m => m >= 10 ? 3 : m >= 3 ? 2 : m >= 1.5 ? 1 : 0;
const trailD = (p, fill) => { let d = ''; for (let i = 0; i <= 24; i++) { const q = p * i / 24; d += (i ? 'L' : 'M') + (8 + q * 70 + 3).toFixed(2) + ' ' + (100 - (12 + 52 * Math.pow(q, 1.6)) - 3).toFixed(2) + ' ' } return fill ? d + `L${(8 + p * 70 + 3).toFixed(2)} 100 L11 100 Z` : d };
function vFoguete() {
  const p = rk.phase;
  const state = p === 'idle' ? 'O foguete decola — saque antes de explodir' : p === 'fly' ? 'Voando… saque antes que exploda' : p === 'crash' ? `Explodiu em x${rk.crash.toFixed(2)} — aposta queimou` : `Sacou em x${rk.m.toFixed(2)} · o foguete chegou até x${rk.crash.toFixed(2)}`;
  return `<div class="rk-hist" aria-label="Últimas rodadas">${(L.rhist || []).map(x => `<span class="${x >= 2 ? 'hi' : ''}">x${x.toFixed(2)}</span>`).join('') || '<span>Ainda não houve rodadas</span>'}</div>
 <div class="sky${p === 'crash' ? ' boom' : p === 'won' ? ' won' : p === 'fly' ? ' fly' : ''}"><svg class="trail" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path id="rfill" class="tf" d="${p === 'idle' ? '' : trailD(rk.pp || 0, true)}"/><path id="rpath" class="tl" d="${p === 'idle' ? '' : trailD(rk.pp || 0)}"/></svg><div class="mult" id="rmul" data-h="${heat(p === 'crash' ? rk.crash : rk.m)}">x${(p === 'crash' ? rk.crash : rk.m).toFixed(2)}</div><div class="rocket" id="rocket" style="${rkPos(p === 'idle' ? 0 : rk.pp || 0)}"><span>🚀</span></div>${p === 'crash' ? '<div class="blast">💥</div>' : ''}<div class="rk-state">${state}</div></div>
 ${p === 'fly' ? `<button class="cta wide" data-rcash id="rcash">Sacar ${money(Math.floor(rk.stake * rk.m))}</button>` : stakeBar() + `<div class="stake"><small>Saque automático</small><div class="stake-row">${AUTOS.map(v => `<button class="st${v === rk.auto ? ' on' : ''}" data-auto="${v}">${v ? 'x' + v : 'off'}</button>`).join('')}</div></div><button class="cta wide" data-rplay>Lançar · ${money(L.stake)}</button>`}
 <p class="rules">O multiplicador sobe enquanto o foguete voa. Saque antes de explodir — recebe aposta × multiplicador. Retorno ao jogador ${Math.round(RTP * 100)}%.</p>`;
}
async function rocketStart() {
  if (S.gold < L.stake) { toast(`Precisa de ${fmt(L.stake)} ouro`); return }
  let res;
  try {
    res = await api('/games/crash/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bet: L.stake }),
    });
  } catch (e) { toast('Erro: ' + e.message); refreshWallet(); return }
  rk = { phase: 'fly', m: 1, pp: 0, crash: res.crash_point, t0: performance.now(), stake: L.stake, auto: L.auto || 0, sid: res.session_id };
  setBal(S.gold - L.stake, S.copper);
  render();
  gameTimers.push(setInterval(rocketTick, 50));
}
function rocketTick() {
  if (rk.phase !== 'fly') return;
  const t = (performance.now() - rk.t0) / 1000, m = Math.floor(Math.exp(0.12 * t) * 100) / 100;
  if (rk.auto && m >= rk.auto) { rk.m = rk.auto; return rocketCash(true) }
  if (m >= rk.crash) { rk.m = rk.crash; return rocketEnd(false) }
  rk.m = m;
  const el = $('#rmul'); if (!el) return;
  el.textContent = 'x' + m.toFixed(2);
  const p = Math.min(1, Math.log(m) / Math.log(8)); rk.pp = p;
  $('#rocket').style.cssText = rkPos(p); el.dataset.h = heat(m);
  $('#rpath').setAttribute('d', trailD(p)); $('#rfill').setAttribute('d', trailD(p, true));
  const c = $('#rcash'); if (c) c.innerHTML = 'Sacar ' + money(Math.floor(rk.stake * m));
}
async function rocketCash(auto = false) {
  if (rk.phase !== 'fly') return;
  rocketTick();
  if (rk.phase !== 'fly') return; // взрыв уже случился в тике
  let res;
  try { res = await api(`/games/crash/cash?session_id=${rk.sid}`, { method: 'POST' }) }
  catch (e) { toast('Erro: ' + e.message); return }
  if (!res.win) return rocketEnd(false, res);
  stopGames();
  rk.phase = 'won'; rk.m = res.m ?? rk.m;
  L.rhist = [rk.crash, ...(L.rhist || [])].slice(0, 12); savePrefs();
  const w = res.payout ?? Math.floor(rk.stake * rk.m);
  setBal(S.gold + w, S.copper);
  const here = tab === 'games' && sub === 'foguete';
  if (here) { render(); fx.win($('.sky'), w, rk.m) }
  toast(pickOne(JOKES.rkWin) + ' · +' + fmt(w) + ' ouro' + (auto ? ' (auto)' : ''));
  refreshWallet();
}
function rocketEnd(busted, res) {
  stopGames();
  rk.phase = 'crash';
  if (res && res.crash) rk.crash = res.crash;
  L.rhist = [rk.crash, ...(L.rhist || [])].slice(0, 12); savePrefs();
  const here = tab === 'games' && sub === 'foguete';
  if (here) { render(); fx.confetti($('.blast'), 60, FIRE); fx.lose($('.sky')) }
  toast(pickOne(JOKES.rkLose) + ' · x' + rk.crash.toFixed(2));
  refreshWallet();
}
function leaveStakeGames() {
  if (rk.phase === 'fly') rocketCash(true);
  if (['show', 'shuffle', 'pick'].includes(thim.phase)) { toast('Aposta perdida — rodada abandonada'); thim.phase = 'idle'; refreshWallet() }
}

/* ---------- profile ---------- */
const REASON_PT = {
  case_open: 'Caixa aberta',
  item_sold: 'Item vendido',
  mines_stake: 'Minas: aposta',
  mines_cashout: 'Minas: saque',
  shell_stake: 'Copos: aposta',
  shell_win: 'Copos: ganho',
  shell_loss: 'Copos: perda',
  crash_stake: 'Foguete: aposta',
  crash_cashout: 'Foguete: saque',
  crash_win: 'Foguete: ganho',
  crash_loss: 'Foguete: perda',
  daily_claim: 'Check-in diário',
  daily_bonus: 'Check-in diário',
  welcome_bonus: 'Bônus de boas-vindas',
  welcome_freebet: 'Bônus de boas-vindas em cobre',
  giftcard_redemption: 'Troca por gift card',
  sandbox_preview: 'Atualização de saldo',
  deposit: 'Depósito',
  deposit_credit: 'Depósito confirmado',
  referral_bonus: 'Bônus de amigo',
};
const reasonText = r => REASON_PT[r] || r;
const plural = (n, a, b, c) => n % 10 === 1 && n % 100 !== 11 ? a : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? b : c;
function vProfile() {
  const done = DAILY.claimed_dates || [];
  const today = new Date().toISOString().slice(0, 10);
  const can = !!DAILY.can_claim;
  const link = WindropCommerce.safeReferralLink(REFS.link) || '';
  const when = t => new Date(t).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  return `<h1 class="title">Perfil</h1>
 <section class="card"><h2>Saldo</h2><div class="bal-grid"><div class="b gold">${coin('gold')}<span><b id="profile-gold">${fmt(S.gold)}</b><small>Ouro: caixas, jogos, aprimoramentos</small></span></div><div class="b copper">${coin('copper')}<span><b id="profile-copper">${fmt(S.copper)}</b><small>Cobre: caixas de freebet</small></span></div></div>
 <p class="note">Ouro vem de depósitos, dos mini-jogos e dos itens vendidos. Cobre — do check-in diário.</p></section>
 <section class="card commerce-form" id="deposit">${commerce.depositView()}</section>
 <section class="card commerce-form" id="withdraw">${commerce.giftView()}</section>
 <section class="card commerce-form" id="personal-bot">${commerce.botsView()}</section>
 <section class="card" id="profile-daily"><div class="card-head"><h2>Check-in diário</h2><span class="pill">Série: ${DAILY.streak || 0} ${plural(DAILY.streak || 0, 'dia', 'dias', 'dias')}</span></div>
 <div class="days">${Array.from({ length: 7 }, (_, k) => {
    const date = new Date(Date.now() - (6 - k) * 864e5).toISOString().slice(0, 10);
    const got = done.includes(date);
    return `<div class="d ${got ? 'got' : ''} ${k === 6 && can ? 'next' : ''}"><small>Dia ${k + 1}</small>${got ? icon('check') : coin('copper')}<b>500</b></div>`;
  }).join('')}</div>
 <p class="hint">Todo dia: +500 🥉. 7 dias seguidos liberam a Caixa Semanal, 30 dias — a Mensal. Pular um dia zera a série.</p>
 <button class="cta" data-claim ${can ? '' : 'disabled'}>${can ? 'Check-in' : 'Já fez hoje — volte amanhã'}</button></section>
 <section class="card" id="profile-referrals"><div class="card-head"><h2>Amigos</h2><span class="pill">${REFS.invited || 0} ${plural(REFS.invited || 0, 'amigo', 'amigos', 'amigos')}</span></div>
 <p class="hint">${link ? 'Bônus quando o amigo depositar pelo seu link.' : 'Link de convite indisponível no momento. Tente novamente mais tarde.'}</p>
 <div class="ref"><input id="reflink" value="${esc(link)}" placeholder="${link ? '' : 'Link de convite indisponível'}" readonly aria-label="Link de convite"><button class="icon-btn" data-copy aria-label="Copiar" ${link ? '' : 'disabled'}>${icon('copy')}</button></div>
 <div class="row"><button class="ghost" data-share ${link ? '' : 'disabled'}>Convidar</button></div>
 <div class="ref-stats"><div class="ref-stat"><span>${REFS.invited || 0}</span><small>convidados</small></div><div class="ref-stat"><span>${REFS.confirmed || 0}</span><small>confirmados</small></div></div></section>
 <section class="card" id="profile-history"><h2>Histórico</h2>${HIST.length ? `<ul class="list hist">${HIST.slice(0, 25).map(h => h.kind === 'item'
    ? `<li><span><b>${esc(h.text)}</b><small>${when(h.t)}</small></span><em class="it">item</em></li>`
    : `<li><span><b>${esc(reasonText(h.text))}</b><small>${when(h.t)}</small></span><em class="${h.delta < 0 ? 'neg' : 'pos'}">${h.delta > 0 ? '+' : ''}${fmt(h.delta)} ${cur(h.currency)}</em></li>`).join('')}</ul>` : '<p class="hint">Ainda vazio.</p>'}</section>`;
}
async function claimDaily() {
  if (!DAILY.can_claim) return;
  try {
    const r = await api('/rewards/daily/claim', { method: 'POST' });
    toast(`+${fmt(r.amount || 500)} cobre${r.streak ? ` · série ${r.streak}` : ''}`);
    await refreshProfile(true);
  } catch (e) { toast('Erro: ' + e.message) }
}

/* ---------- events ---------- */
document.addEventListener('click', e => {
  if (e.target.closest('a[data-payment-link]')) { if (!commerce.allowPaymentLink()) e.preventDefault(); return; }
  const b = e.target.closest('button'); if (!b || b.disabled) return;
  const d = b.dataset;
  if (d.initretry !== undefined) return initialize(true);
  if (d.tab) return go(d.tab);
  if (initialState !== 'ready') return;
  if (commerce.handleClick(d)) return;
  if (d.back !== undefined) return go(tab);
  if (d.cat) { cat = d.cat; return render() }
  if (d.case) return go('cases', d.case);
  if (d.open !== undefined) return openCase(d.open);
  if (d.close !== undefined) return closeModal();
  if (d.sell) { sell(Number(d.sell)); return }
  if (d.sellall !== undefined) return sellAll();
  if (d.toup) { upSel = Number(d.toup); upTarget = null; return go('upgrade') }
  if (d.upsel) { if (upBusy) return; upSel = Number(d.upsel); upTarget = null; return render() }
  if (d.uptgt) {
    if (upBusy) return;
    const sel = mine().find(i => i.id === upSel);
    const item = CATALOG.flatMap(c => c.rewards).find(i => i.rid === Number(d.uptgt));
    if (sel && item) upTarget = { rid: item.rid, name: item.name, value: item.value, image: item.image, tier: item.tier };
    return render();
  }
  if (d.upgo !== undefined) return doUpgrade();
  if (d.game) return go('games', d.game);
  if (d.stake !== undefined) { L.stake = Number(d.stake); savePrefs(); return render() }
  if (d.minecount !== undefined) { L.mineCount = Number(d.minecount); savePrefs(); return render() }
  if (d.mplay !== undefined) return minesStart();
  if (d.cell !== undefined) return minesOpen(Number(d.cell));
  if (d.mcash !== undefined) return minesCash();
  if (d.tplay !== undefined) return coposStart();
  if (d.cup !== undefined) return coposPick(Number(d.cup));
  if (d.rplay !== undefined) return rocketStart();
  if (d.rcash !== undefined) return rocketCash();
  if (d.auto !== undefined) { rk.auto = L.auto = Number(d.auto); savePrefs(); return render() }
  if (d.claim !== undefined) return claimDaily();
  if (d.copy !== undefined || d.share !== undefined) {
    const v = WindropCommerce.safeReferralLink(REFS.link);
    if (!v) { toast('Link de convite indisponível no momento.'); return; }
    const input = $('#reflink');
    if (input) input.value = v;
    if (d.share !== undefined && navigator.share) { navigator.share({ title: 'WINDROP', url: v }).catch(() => {}); return }
    (navigator.clipboard ? navigator.clipboard.writeText(v) : Promise.reject()).then(() => toast('Link copiado')).catch(() => {
      const current = $('#reflink');
      if (current && WindropCommerce.safeReferralLink(REFS.link) === v) { current.value = v; current.select(); toast('Selecione e copie o link'); }
    });
    return;
  }
});
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal() });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#modal').hidden) closeModal() });
document.addEventListener('input', e => { if (e.target.id === 'dep-amount') commerce.setAmount(e.target.value); });
document.addEventListener('change', e => { if (e.target.id === 'wd-card') commerce.setSku(e.target.value); });
document.addEventListener('visibilitychange', () => {
  commerce.visibilityChanged();
  renderBal();
  if (document.hidden) { savePrefs(); stopGames(); }
});
window.addEventListener('pagehide', () => commerce.dispose());
window.addEventListener('pageshow', e => { if (e.persisted) window.location.reload(); });

/* ---------- init ---------- */
function initialize(retry = false) {
  if (initialPromise) return initialPromise;
  initialState = 'loading'; initialError = ''; renderBal(); render();
  initialPromise = (async () => {
    let authenticated = false;
    try {
      if (retry) await apiClient.retryAuthentication(); else await apiClient.authenticate();
      authenticated = true;
      await Promise.all([refreshWallet(), loadCatalog()]);
      initialState = 'ready'; render(); scrollProfileTarget();
      // Профильные необязательные запросы не блокируют первый экран кейсов.
      void Promise.allSettled([refreshInv(), refreshDaily(), refreshRefs(), refreshHist(), applyBrand()]);
    } catch (error) {
      initialState = 'error'; initialAuthError = !authenticated || error.status === 401;
      initialError = WindropApi.errorMessage(error); render();
    } finally { initialPromise = null; }
  })();
  return initialPromise;
}
void initialize();
