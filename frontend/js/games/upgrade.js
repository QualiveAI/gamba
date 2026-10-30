async function loadUpgradeCatalog() {
  const catalog = await window.api("/cases");
  const fromSel = document.getElementById("upgrade-from");
  const toSel = document.getElementById("upgrade-to");
  if (fromSel) {
    fromSel.innerHTML = catalog.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
  }
  if (toSel) {
    toSel.innerHTML = catalog.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
  }
}

async function spinUpgrade() {
  const fromId = document.getElementById("upgrade-from").value;
  const toId = document.getElementById("upgrade-to").value;
  const res = await window.api("/games/upgrade/spin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from_prize_id: fromId, to_prize_id: toId }),
  });
  const resultEl = document.getElementById("upgrade-result");
  if (resultEl) resultEl.textContent = res.success ? "UPGRADED!" : "Failed";
}

window.loadUpgradeCatalog = loadUpgradeCatalog;
window.spinUpgrade = spinUpgrade;