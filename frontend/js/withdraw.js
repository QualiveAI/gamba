// Вывод: только картами фиксированных номиналов. 1 монетка = 1₽.
// Комиссия вывода удерживается из суммы (комиссии на стороне клиента).
const WD_CARDS = [
  { usd: 10, coins: 1000 },
  { usd: 25, coins: 2500 },
  { usd: 50, coins: 5000 },
  { usd: 100, coins: 10000 },
];

function wdTotal() {
  const nominal = parseInt(document.getElementById("wd-card").value, 10) || 1000;
  const count = Math.max(1, parseInt(document.getElementById("wd-count").value, 10) || 1);
  return { nominal, count, total: nominal * count };
}

function updateWithdrawPreview() {
  const { nominal, count, total } = wdTotal();
  const el = document.getElementById("wd-preview");
  if (!el) return;
  const gross = total * 0.015;
  el.innerHTML =
    `Saque: <b>${total} 🪙</b> = <b>$${gross.toFixed(2)}</b> • ` +
    `no cartão: <b>$${(gross * 0.8).toFixed(2)}</b>`;
}

async function submitWithdraw() {
  const { total } = wdTotal();
  const region = document.getElementById("wd-region").value || "BR";
  const resultEl = document.getElementById("wd-result");
  if (total < 1000) {
    if (resultEl) resultEl.textContent = "Saque mínimo — 1 000 🪙 (cartão $10)";
    return;
  }
  try {
    const r = await window.api("/withdrawals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount: total, region }),
    });
    if (resultEl) resultEl.textContent = "Solicitação criada, em análise";
    const pid = r.id || r.withdrawal_id;
    if (pid) pollWithdrawStatus(pid);
  } catch (e) {
    if (resultEl) resultEl.textContent = "Ошибка: " + e.message;
  }
}

function pollWithdrawStatus(pid) {
  const statusEl = document.getElementById("wd-status");
  const interval = setInterval(async () => {
    try {
      const st = await window.api(`/withdrawals/${pid}/status`);
      if (statusEl) statusEl.textContent = st.status;
      if (["completed", "rejected", "failed"].includes(st.status)) clearInterval(interval);
    } catch (e) {
      clearInterval(interval);
    }
  }, 3000);
}

async function loadWithdrawLimits() {
  updateWithdrawPreview();
}

window.loadWithdrawLimits = loadWithdrawLimits;
window.submitWithdraw = submitWithdraw;
window.updateWithdrawPreview = updateWithdrawPreview;
