// Mochila (инвентарь): предметы из кейсов — продать, апгрейднуть или вывести
const RARITY_CLS = { Legendary: "r-legendary", Epic: "r-epic", Rare: "r-rare", Uncommon: "r-uncommon", Common: "r-common", Upgraded: "r-epic" };

async function loadInventory() {
  const list = document.getElementById("inv-list");
  if (!list) return;
  let items = [];
  try {
    items = await window.api("/inventory");
  } catch (e) { /* пусто */ }
  list.innerHTML = "";
  let totalUnits = 0;
  items.forEach((it) => {
    if (it.currency === "units") totalUnits += it.value_coins;
    const card = document.createElement("div");
    card.className = "inv-item " + (RARITY_CLS[it.rarity] || "r-common");
    const imgMap = { Legendary: "item_robux_1000.png", Epic: "item_robux_250.png", Rare: "item_robux_100.png", Uncommon: "item_robux_50.png", Common: "item_robux_10.png", Upgraded: "item_robux_1000.png" };
    card.innerHTML =
      `<img class="inv-img" src="assets/${imgMap[it.rarity] || "item_robux_10.png"}" alt="" />` +
      `<div class="inv-label">${it.label}</div>` +
      `<div class="inv-price">${it.value_coins} ${it.currency === "units" ? "🪙" : "🥉"}</div>` +
      `<div class="cell-rarity">${it.rarity}</div>`;
    const btns = document.createElement("div");
    btns.className = "inv-btns";
    const up = document.createElement("button");
    up.className = "inv-btn";
    up.textContent = "⚡";
    up.title = "Upgrade";
    up.addEventListener("click", () => openUpgradeFor(it));
    btns.appendChild(up);
    card.appendChild(btns);
    list.appendChild(card);
  });
  const totalEl = document.getElementById("inv-total");
  if (totalEl) totalEl.textContent = `Valor total: ${totalUnits} 🪙`;
  if (!items.length) list.innerHTML = '<div class="toast">Mochila vazia — abra caixas!</div>';
}

// Апгрейд выбранного предмета
let upgradeItemId = null;

function openUpgradeFor(item) {
  upgradeItemId = item.id;
  window.showScreen("upgrade");
  const sel = document.getElementById("up-item");
  if (sel) {
    sel.innerHTML = `<option value="${item.id}" data-value="${item.value_coins}">${item.label} (${item.value_coins} 🪙)</option>`;
  }
  const t = document.getElementById("upgrade-target-price");
  if (t) { t.value = Math.round(item.value_coins * 2); previewUpgradeChance(); }
  const res = document.getElementById("upgrade-result");
  if (res) res.textContent = "";
}

window.loadInventory = loadInventory;
window.openUpgradeFor = openUpgradeFor;
