// Кейсы: карточки по топ-играм + фрибет-кейсы, рулетка-анимация открытия,
// лайв-лента дропов. Редкости по отношению номинала к цене кейса.

const CASE_EMOJI = {
  brainrot: "🧠", bloxfruits: "🍉", growagarden: "🌻", brookhaven: "🏙️",
  adoptme: "🐶", "99nights": "🏕️", rivals: "⚔️", dti: "👗",
  mm2: "🔪", petsim99: "🐾",
  daily_fb: "🥉", weekly_fb: "📦", mega_fb: "💎",
};

const RARITY = [
  { min: 0, name: "Common", cls: "r-common" },
  { min: 0.5, name: "Uncommon", cls: "r-uncommon" },
  { min: 1.0, name: "Rare", cls: "r-rare" },
  { min: 2.0, name: "Epic", cls: "r-epic" },
  { min: 5.0, name: "Legendary", cls: "r-legendary" },
];

let casesCache = [];
let activeTab = "units";

function caseBadge(c) {
  const gk = c.rewards && c.rewards[0] && c.rewards[0].game_key;
  return CASE_EMOJI[gk] || "📦";
}

function rarityClass(caseInfo, nominal) {
  const ratio = nominal / Math.max(1, caseInfo.price_units);
  let cls = RARITY[0].cls;
  for (const r of RARITY) if (ratio >= r.min) cls = r.cls;
  return cls;
}

function rarityName(caseInfo, nominal) {
  const ratio = nominal / Math.max(1, caseInfo.price_units);
  let name = RARITY[0].name;
  for (const r of RARITY) if (ratio >= r.min) name = r.name;
  return name;
}

async function loadCases() {
  try {
    casesCache = await window.api("/cases");
  } catch (e) {
    casesCache = [];
  }
  renderCaseTabs();
  renderCases();
  loadWinFeed();
}

function renderCaseTabs() {
  const tabs = document.getElementById("case-tabs");
  if (!tabs) return;
  tabs.innerHTML = "";
  [["units", "🎮 Jogos"], ["freebets", "🎁 Grátis"]].forEach(([key, label]) => {
    const b = document.createElement("button");
    b.className = "case-tab" + (activeTab === key ? " active" : "");
    b.textContent = label;
    b.addEventListener("click", () => {
      activeTab = key;
      renderCaseTabs();
      renderCases();
    });
    tabs.appendChild(b);
  });
}

function renderCases() {
  const grid = document.getElementById("cases-list");
  if (!grid) return;
  grid.innerHTML = "";
  casesCache
    .filter((c) => (c.currency || "units") === activeTab)
    .forEach((c) => {
      const card = document.createElement("div");
      card.className = "case";
      const badge = (c.rewards && c.rewards[0] && c.rewards[0].game_key) || "case";
      const cur = c.currency === "freebets" ? "🥉" : "🪙";
      const cover = `assets/case_${badge === "case" ? "brainrot" : badge}.png`;
      const onerr = `this.onerror=null;this.src='assets/coin_gold.png'`;
      card.innerHTML =
        `<img class="case-cover" src="${cover}" onerror="${onerr}" alt="${c.name}" />` +
        `<div class="case-title">${c.name}</div>` +
        `<div class="case-price">${c.price_units} ${cur}</div>`;
      const btn = document.createElement("button");
      btn.textContent = c.currency === "freebets" ? "Abrir (grátis)" : "Abrir";
      btn.addEventListener("click", () => openCaseRoulette(c));
      card.appendChild(btn);
      grid.appendChild(card);
    });
  if (!grid.children.length) grid.innerHTML = '<div class="toast">Nenhuma caixa ainda</div>';
}

// ---------- Лайв-лента ----------

async function loadWinFeed() {
  const feed = document.getElementById("win-feed");
  if (!feed) return;
  let items = [];
  try {
    items = await window.api("/rewards/winfeed?limit=15");
  } catch (e) {
    items = [];
  }
  feed.innerHTML = "";
  (items || []).forEach((w) => {
    const el = document.createElement("div");
    el.className = "feed-item " + rarityClass({ price_units: 300 }, w.amount_units || 0);
    el.innerHTML = `<span class="feed-game">${w.game || "case"}</span> <span class="feed-amount">+${w.amount_units}</span>`;
    feed.appendChild(el);
  });
  if (!feed.children.length) feed.innerHTML = '<div class="feed-item">Seja o primeiro a jogar!</div>';
}

// ---------- Рулетка открытия ----------

async function openCaseRoulette(caseInfo) {
  const overlay = document.getElementById("roulette-overlay");
  const strip = document.getElementById("roulette-strip");
  const resultBox = document.getElementById("roulette-result");
  if (!overlay || !strip) return;
  resultBox.textContent = "";
  resultBox.className = "roulette-result";
  overlay.classList.add("open");

  let res;
  try {
    res = await window.api(`/cases/${caseInfo.id}/open`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_seed: crypto.randomUUID() }),
    });
  } catch (e) {
    overlay.classList.remove("open");
    alert(e.message);
    return;
  }

  // Стрелка попадает в центр элемента с индексом WIN_INDEX
  const WIN_INDEX = 32;
  const prizes = caseInfo.rewards || [];
  const totalW = prizes.reduce((s, p) => s + Number(p.weight), 0);

  strip.innerHTML = "";
  const items = [];
  for (let i = 0; i < 48; i++) {
    if (i === WIN_INDEX) {
      items.push({ nominal: res.nominal_units, label: res.item, fixed: true });
      continue;
    }
    let roll = Math.random() * totalW;
    let chosen = prizes[prizes.length - 1];
    for (const p of prizes) {
      roll -= Number(p.weight);
      if (roll <= 0) { chosen = p; break; }
    }
    items.push({ nominal: chosen.nominal_units });
  }

  items.forEach((it) => {
    const cell = document.createElement("div");
    const rc = rarityClass(caseInfo, it.nominal);
    cell.className = "roulette-cell " + rc;
    cell.innerHTML =
      `<div class="cell-emoji">${CASE_EMOJI[caseInfo.game_badge] || "📦"}</div>` +
      `<div class="cell-value">${it.nominal}</div>` +
      `<div class="cell-rarity">${rarityName(caseInfo, it.nominal)}</div>`;
    strip.appendChild(cell);
  });

  // Ширина ячейки + gap, наводим центр окна на WIN_INDEX (+ небольшой сдвиг внутри ячейки)
  const CELL = 96 + 8;
  const jitter = (Math.random() * 0.5 - 0.25) * 60;
  const target = WIN_INDEX * CELL + CELL / 2 + jitter;
  strip.style.transition = "none";
  strip.style.transform = "translateX(0)";
  void strip.offsetWidth; // reflow
  strip.style.transition = "transform 4.2s cubic-bezier(0.12, 0.75, 0.06, 1)";
  strip.style.transform = `translateX(-${target}px)`;

  setTimeout(() => {
    const winCls = rarityClass(caseInfo, res.nominal_units);
    resultBox.className = "roulette-result " + winCls;
    resultBox.textContent =
      `${res.item || "Предмет"} — +${res.credit_units ?? res.nominal_units} ` +
      (caseInfo.currency === "freebets" ? "🥉 cobre" : "🪙 ouro") +
      ` (${rarityName(caseInfo, res.nominal_units)})`;
    if (window.showReaction) {
      const ratio = res.nominal_units / Math.max(1, caseInfo.price_units);
      window.showReaction(
        "cases-reaction",
        ratio >= 2 ? "victory" : ratio >= 1 ? "showoff" : "tilt",
      );
    }
    if (window.renderWallet) window.renderWallet();
    loadWinFeed();
  }, 4400);
}

function closeRoulette() {
  document.getElementById("roulette-overlay").classList.remove("open");
}

window.loadCases = loadCases;
window.closeRoulette = closeRoulette;


// Детальный просмотр кейса: предметы + % выпадения
function showCaseDetail(c) {
  const box = document.getElementById("roulette-box");
  const overlay = document.getElementById("roulette-overlay");
  const strip = document.getElementById("roulette-strip");
  const resultBox = document.getElementById("roulette-result");
  strip.innerHTML = "";
  strip.style.transform = "none";
  resultBox.className = "roulette-result";
  const rewards = (c.rewards || []).slice().sort((a, b) => Number(a.nominal_units) - Number(b.nominal_units));
  const total = rewards.reduce((acc, r) => acc + Number(r.weight), 0);
  const badge3 = (c.rewards && c.rewards[0] && c.rewards[0].game_key) || "brainrot";
  rewards.forEach((r, idx) => {
    const pct = (Number(r.weight) / total * 100);
    const row = document.createElement("div");
    row.className = "detail-row " + rarityClass(c, Number(r.nominal_units));
    const img = `assets/item_${badge3}_${idx + 1}.png`;
    row.innerHTML =
      `<img class="detail-img" src="${img}" onerror="this.onerror=null;this.src='assets/coin_gold.png'" alt="" />` +
      `<span>${r.label}</span><b>${pct >= 1 ? pct.toFixed(1) : pct.toFixed(3)}%</b>` +
      `<i>${r.nominal_units} ${c.currency === "freebets" ? "🥉" : "🪙"}</i>`;
    strip.appendChild(row);
  });
  strip.classList.add("detail-mode");
  resultBox.textContent = c.name + " — " + c.price_units + (c.currency === "freebets" ? " 🥉" : " 🪙");
  overlay.classList.add("open");
}
window.showCaseDetail = showCaseDetail;
