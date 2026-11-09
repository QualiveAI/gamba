// Upgrade: POST /games/upgrade {item_price, target_price, client_seed}
// -> {success, chance, roll}. Шанс = item_price/target_price*0.8.

async function spinUpgrade() {
  const itemPrice = parseInt(document.getElementById("upgrade-item-price").value, 10) || 100;
  const targetPrice = parseInt(document.getElementById("upgrade-target-price").value, 10) || 200;
  const resultEl = document.getElementById("upgrade-result");
  try {
    const res = await window.api("/games/upgrade", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        item_price: itemPrice,
        target_price: targetPrice,
        client_seed: crypto.randomUUID(),
      }),
    });
    if (resultEl) {
      const chancePct = Math.round((res.chance || 0) * 100);
      resultEl.textContent =
        (res.success ? "АПГРЕЙД УДАЛСЯ!" : "Не удалось") +
        ` (шанс ${chancePct}%, ролл ${(res.roll || 0).toFixed(3)})`;
    }
    if (window.showReaction)
      window.showReaction("upgrade-reaction", res.success ? "showoff" : "tilt");
  } catch (e) {
    if (resultEl) resultEl.textContent = "Ошибка: " + e.message;
  }
}

// Живое превью шанса: chance = item/target * 0.8
function previewUpgradeChance() {
  const itemPrice = parseInt(document.getElementById("upgrade-item-price").value, 10) || 0;
  const targetPrice = parseInt(document.getElementById("upgrade-target-price").value, 10) || 0;
  const resultEl = document.getElementById("upgrade-result");
  if (resultEl && itemPrice > 0 && targetPrice > 0) {
    const chance = Math.min(0.8, (itemPrice / targetPrice) * 0.8) * 100;
    resultEl.textContent = "Шанс апгрейда: " + Math.round(chance) + "%";
  }
}
window.previewUpgradeChance = previewUpgradeChance;
window.spinUpgrade = spinUpgrade;
