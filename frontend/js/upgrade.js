// Upgrade: выбираешь предмет из мошны, цель в монетках, шанс = value/target * 0.8.
// Успех — предмет становится дороже, провал — предмет теряется.

function upgradeTargetValue() {
  return parseInt(document.getElementById("upgrade-target-price").value, 10) || 0;
}

function previewUpgradeChance() {
  const sel = document.getElementById("up-item");
  const resultEl = document.getElementById("upgrade-result");
  const target = upgradeTargetValue();
  let value = 0;
  if (sel && sel.selectedOptions[0]) value = parseInt(sel.selectedOptions[0].dataset.value, 10) || 0;
  if (resultEl && value > 0 && target > value) {
    const chance = Math.min(0.8, (value / target) * 0.8) * 100;
    resultEl.textContent = "Chance: " + Math.round(chance) + "%";
  } else if (resultEl) {
    resultEl.textContent = "Escolha um alvo maior que o item";
  }
}

async function spinUpgrade() {
  const sel = document.getElementById("up-item");
  const resultEl = document.getElementById("upgrade-result");
  if (!sel || !sel.value) {
    if (resultEl) resultEl.textContent = "Selecione um item na mochila";
    return;
  }
  const target = upgradeTargetValue();
  try {
    const res = await window.api(`/inventory/${sel.value}/upgrade`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_value: target }),
    });
    if (res.success) {
      resultEl.textContent = `⚡ UPGRADE! Item agora vale ${res.value} 🪙 (roll ${(res.roll).toFixed(3)})`;
      if (window.showReaction) window.showReaction("upgrade-reaction", "showoff");
    } else {
      resultEl.textContent = `Perdeu... (roll ${(res.roll).toFixed(3)} vs chance ${Math.round(res.chance * 100)}%)`;
      if (window.showReaction) window.showReaction("upgrade-reaction", "tilt");
    }
  } catch (e) {
    if (resultEl) resultEl.textContent = "Erro: " + e.message;
  }
}

window.previewUpgradeChance = previewUpgradeChance;
window.spinUpgrade = spinUpgrade;
